import re

import pytesseract
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import FileResponse
import uvicorn
from typing import List

app = FastAPI()

# ===== 解析标准答案 =====
def parse_answers(content: str):
    result = {}
    for line in content.strip().split("\n"):
        if "." in line:
            num, ans = line.split(".")
            result[num.strip()] = ans.strip()
    return result

# ===== 模拟 OCR（稳定版本）=====
from paddleocr import PaddleOCR
import re
from PIL import Image

# 👉 初始化（只会加载一次）
ocr = PaddleOCR(use_angle_cls=True, lang="ch")

def ocr_recognition(file, correct_answers):
    try:
        from collections import Counter
        import re
        from PIL import Image

        image = Image.open(file.file)
        image_path = "temp.jpg"
        image.save(image_path)

        result = ocr.ocr(image_path, cls=True)

        # ================================
        # 1️⃣ 收集所有 OCR 文本（带坐标）
        # ================================
        words = []

        for line in result:
            for word in line:
                text = word[1][0].strip()
                score = word[1][1]

                x = word[0][0][0]
                y = word[0][0][1]

                words.append({
                    "text": text,
                    "x": x,
                    "y": y,
                    "score": score
                })

        # 👉 按 y 排序（从上到下）
        words.sort(key=lambda w: w["y"])

        # ================================
        # 2️⃣ 找题号（关键！）
        # ================================
        questions = []

        for w in words:
            match = re.match(r"^(\d+)[\.\、]?", w["text"])
            if match:
                q_num = match.group(1)

                # 只保留有效题号
                if q_num in correct_answers:
                    questions.append({
                        "q_num": q_num,
                        "y": w["y"]
                    })

        # 👉 按 y 排序题号
        questions.sort(key=lambda q: q["y"])

        # ================================
        # 3️⃣ 切分题目块
        # ================================
        blocks = []

        for i in range(len(questions)):
            start_y = questions[i]["y"]
            end_y = questions[i+1]["y"] if i < len(questions)-1 else 99999

            blocks.append({
                "q_num": questions[i]["q_num"],
                "start_y": start_y,
                "end_y": end_y
            })

        # ================================
        # 4️⃣ 从每个块中提取答案
        # ================================
        student_answers = {}

        for block in blocks:
            candidates = []

            # =========================
            # 1️⃣ 找选项开始位置（增强版）
            # =========================
            option_y = None
            option_count = 0

            for w in words:
                if block["start_y"] <= w["y"] < block["end_y"]:
                    text = w["text"].upper().strip()

                    if re.match(r"^[A-D][\.\、．]", text):
                        option_count += 1

                        # 👉 连续出现 >=2 个选项 → 才认为进入选项区
                        if option_count >= 2:
                            option_y = w["y"]
                            break
                    else:
                        option_count = 0
                        option_y = w["y"]


            if option_y is None:
                option_y = block["end_y"]

            # =========================
            # 2️⃣ 在题干区域找答案
            # =========================
            for w in words:
                if block["start_y"] <= w["y"] < option_y:
                    text = w["text"].upper().strip()

                    # 👉 手写容错（关键）
                    

                    # 👉 过滤太长的
                    if len(text) > 6:
                        continue

                    print("识别:", text)  # 调试

                    # 👉 括号答案优先
                    match = re.search(r"[（(]\s*([A-D])\s*[）)]", text)
                    if match and w["score"] > 0.5:
                        candidates.append(match.group(1))
                        continue

                    # 👉 提取任意字母（核心升级）
                    match_letter = re.search(r"[A-D]", text)
                    if match_letter and w["score"] > 0.5:
                        candidates.append(match_letter.group(0))

            # =========================
            # 3️⃣ 投票
            # =========================
            print("题号:", block["q_num"], "候选:", candidates)
            if candidates:
                most_common = Counter(candidates).most_common(1)[0][0]
                student_answers[block["q_num"]] = most_common
                
        print("最终答案：", student_answers)

        if len(student_answers) == 0:
            return {}

        return student_answers
    except Exception as e:
        # 捕获异常并返回空字典
        print("OCR识别异常：", e)
        return {}
        
# ===== 批改接口 =====
@app.post("/api/correct")
async def correct_homework(
    answer_file: UploadFile = File(...),
    homework_files: List[UploadFile] = File(...),
    count: int = Form(1)
):
    answer_content = (await answer_file.read()).decode("utf-8")
    correct_answers = parse_answers(answer_content)

    results = []
    num_to_process = min(len(homework_files), count)

    for i in range(num_to_process):
        homework_files[i].file.seek(0)

        student_answers = ocr_recognition(homework_files[i], correct_answers)

        if not student_answers:
            return {"error": "OCR识别失败"}

        homework_result = []

        for q_num, correct_ans in correct_answers.items():
            stu_ans = student_answers.get(q_num, "")

            status = "✅"

            if not stu_ans:
                status = "⚠️"
            elif stu_ans.upper() != correct_ans.upper():
                status = "❌"

            homework_result.append({
                "id": q_num,
                "student_ans": stu_ans or "空",
                "correct_ans": correct_ans,
                "status": status
            })
        
        # 👉 先算分数（加在这里！！）
        score = sum(1 for x in homework_result if x["status"] == "✅")
        total = len(homework_result)
        accuracy = round(score / total * 100, 1)

        results.append({
            "filename": homework_files[i].filename,
            "score": score,
            "total": total,
            "accuracy": accuracy,
            "data": homework_result
        })

    print("返回结果：", results)

    return {
        "success": True,
        "results": results
    }

# ===== 首页 =====
@app.get("/")
def read_index():
    return FileResponse("index.html")

# ===== 启动 =====
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)