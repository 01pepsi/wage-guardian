"""
임금 지킴이 Agent (agent.py)
- Gemini 함수 호출(Function Calling)로 Agent가 스스로 계획 → 도구 선택 → 실행 → 검증
- 금액은 wage_calc(코드)만 계산, 근거는 laws(검색 결과)만 인용
- trace: 화면 타임라인용 실행 기록 (📋계획 🔧도구 🧠판단 ❓질문 🛡️검증 🔁재시도 ✅결과)
CLI 테스트: py agent.py samples/T10.png
"""
import json
import re
import sys
from google.genai import types

from llm import generate
from extractor import extract_payslip, validate_extraction, PayslipData
from wage_calc import WageInput, calculate, WEEKS_PER_MONTH, REQUIRED
from laws import search_law, find_support_center

LANG_NAMES = {"ko": "한국어", "vi": "Tiếng Việt(베트남어)", "ne": "नेपाली(네팔어)",
              "id": "Bahasa Indonesia(인도네시아어)", "km": "ភាសាខ្មែរ(크메르어)", "en": "English(영어)"}

# 사용자에게 물어볼 수 있는 항목과 선택지 (답은 코드가 그대로 저장 → AI가 바꿀 수 없음)
ASK_FIELDS = {
    "employees_5plus": {"label": "사업장 상시근로자 5인 이상 여부",
                        "options": {"5명 이상": True, "5명 미만": False}},
    "weekly_contract_hours": {"label": "주 소정근로시간",
                              "options": {"주 40시간": 40, "주 35시간": 35, "주 30시간": 30, "주 20시간": 20}},
    "pay_type": {"label": "임금 형태", "options": {"시급제": "hourly", "월급제": "monthly"}},
    "housing_type": {"label": "숙소 형태",
                     "options": {"아파트·주택 + 식사 제공": "house_with_meals",
                                 "컨테이너 등 임시숙소 + 식사 제공": "temporary_with_meals",
                                 "아파트·주택 (숙소만)": "house_only",
                                 "임시숙소 (숙소만)": "temporary_only"}},
    "housing_consent": {"label": "숙식비 공제 서면 동의 여부",
                        "options": {"서면으로 동의했어요": True, "동의한 적 없어요": False}},
    "confirm_extraction": {"label": "추출값 확인",
                           "options": {"맞아요": True, "틀린 값이 있어요": False}},
}

SYSTEM_PROMPT = """너는 경남 외국인 근로자의 임금 체불을 찾아 구제까지 돕는 '임금 지킴이' AI Agent다.
목표: 사용자가 올린 급여명세서로 받아야 할 임금을 제대로 받았는지 확인하고, 못 받았다면 돌려받는 방법을 안내한다.

작업 방식 (무료 사용량이 적으니 한 번의 응답에서 여러 도구를 함께 호출해 단계 수를 줄인다):
1. 첫 응답에서 make_plan, extract_payslip, calculate_wage를 순서대로 함께 호출한다.
2. 검산 문제(validation_issues)가 있으면 ask_user로 confirm_extraction을 묻는다.
3. calculate_wage가 'missing'을 돌려주면 ask_fields에 있는 항목만 ask_user 한 번에 모두 묻고(fields 배열), 답을 받으면 다시 calculate_wage를 호출한다.
4. 계산이 끝나면 위반 항목의 근거를 search_law로 찾고, 위반이 있으면 find_support_center도 같은 응답에서 함께 호출한다. 위반이 없으면 상담기관 검색은 생략한다.
5. 마지막에 도구 호출 없이 최종 답변을 쓴다.

반드시 지킬 규칙:
- 금액을 스스로 계산하거나 추측하지 마라. 금액은 calculate_wage 결과에 있는 숫자만 그대로 쓴다.
- 법 조문은 search_law 결과의 id만 인용한다. 결과에 없는 조문 번호를 만들지 마라.
- 사업장 규모, 숙소 형태, 동의 여부 등은 추측하지 말고 ask_user로 묻는다.
- calculate_wage의 ask_fields에 없는 항목은 묻지 않는다. inferred(시스템 추정값)도 다시 묻지 않는다.
- 모든 도구 호출의 reason에는 '왜 지금 이 도구를 쓰는지'를 한국어 한 문장으로 적는다.

최종 답변 형식 ({lang}로 작성, 초등학생도 이해할 쉬운 문장):
- 한 줄 결론 (받지 못한 총액)
- 항목별 설명 (항목명, 받지 못한 금액, 이유, 근거 조문)
- 다음에 할 일 (진정서 만들기, 상담기관)
- 마지막 줄: "이 결과는 참고용이며, 최종 판단은 고용노동부 또는 공인노무사에게 확인하세요."
그 다음 줄에 '[한국어 요약]'을 붙이고 한국어로 3줄 요약한다."""


def _fn(name, desc, props, required=()):
    props = {"reason": {"type": "string", "description": "지금 이 도구를 호출하는 이유 (한국어 한 문장)"}, **props}
    return types.FunctionDeclaration(
        name=name, description=desc,
        parameters_json_schema={"type": "object", "properties": props, "required": ["reason", *required]})


TOOLS = types.Tool(function_declarations=[
    _fn("make_plan", "이번 상황에 맞는 실행 계획(단계 목록)을 세운다.",
        {"steps": {"type": "array", "items": {"type": "string"}, "description": "실행할 단계를 순서대로"}}, ["steps"]),
    _fn("extract_payslip", "업로드된 급여명세서 사진에서 항목을 읽고 합계를 검산한다.", {}),
    _fn("ask_user", "판단에 필요한 정보를 사용자에게 한 번에 묻는다. 선택지는 시스템이 제공한다.",
        {"fields": {"type": "array", "items": {"type": "string", "enum": list(ASK_FIELDS.keys())},
                    "description": "물어볼 항목들"},
         "questions": {"type": "array", "items": {"type": "string"},
                       "description": "fields와 같은 순서의, 사용자 언어로 된 쉬운 질문들"}}, ["fields", "questions"]),
    _fn("calculate_wage", "추출값과 사용자 답변으로 받아야 할 임금과 미지급액을 계산한다. 필요한 정보가 없으면 missing을 돌려준다.", {}),
    _fn("search_law", "판단 근거가 되는 법 조문을 검색한다.",
        {"query": {"type": "string", "description": "검색어 (예: 연장근로 가산수당)"}}, ["query"]),
    _fn("find_support_center", "사업장 주소로 관할 노동청과 상담기관을 찾는다.",
        {"region": {"type": "string", "description": "사업장 주소 또는 시군 이름"}}, ["region"]),
])


class WageAgent:
    def __init__(self, image_bytes: bytes, mime_type: str = "image/png", language: str = "ko",
                 extracted: PayslipData | None = None, generate_fn=None, extract_fn=None):
        """extracted: 사용자가 표에서 고친 값(있으면 사진 인식 생략)
        generate_fn / extract_fn: 데모 모드에서 저장된 응답으로 바꿔 끼우기 위한 자리"""
        self.image_bytes, self.mime_type, self.language = image_bytes, mime_type, language
        self.generate_fn = generate_fn or generate
        self.extract_fn = extract_fn or extract_payslip
        self.extracted: PayslipData | None = extracted
        self.answers: dict = {}
        self.inferred: dict = {}
        self.result = None            # WageResult
        self.retrieved_law_ids: set = set()
        self.centers: list = []
        self.plan: list = []
        self.trace: list = []
        self.history: list = []
        self.pending = None           # {"parts": [...], "queue": [질문들], "answers": {}}
        self.final_text = None
        self.model = None
        self.config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT.format(lang=LANG_NAMES.get(language, "한국어")),
            tools=[TOOLS],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0,
        )

    # ---------- 기록 ----------
    def log(self, kind, title, detail=None):
        icons = {"goal": "🎯", "plan": "📋", "tool": "🔧", "think": "🧠", "ask": "❓",
                 "verify": "🛡️", "retry": "🔁", "result": "✅", "error": "⚠️"}
        self.trace.append({"kind": kind, "icon": icons.get(kind, "•"), "title": title, "detail": detail})

    # ---------- 실행 ----------
    def start(self):
        self.log("goal", "목표: 급여명세서로 받아야 할 임금을 받았는지 확인하고, 못 받았다면 구제 방법 안내")
        self.history = [types.Content(role="user", parts=[types.Part(text=
            f"급여명세서 사진을 올렸어요. 제 임금이 맞게 나왔는지 확인해 주세요. 답변 언어: {LANG_NAMES.get(self.language)}")])]
        return self._loop()

    def answer(self, option_label: str):
        """ask_user 질문에 대한 사용자 선택을 받아 Agent를 이어서 실행"""
        p = self.pending
        q = p["queue"].pop(0)
        field = q["field"]
        value = ASK_FIELDS[field]["options"][option_label]
        if field == "confirm_extraction" and not value:
            self.log("think", "사용자가 추출값이 틀렸다고 답함 → 값을 고친 뒤 다시 분석해야 함")
            self.final_text = "읽은 값 중 틀린 부분을 화면의 표에서 고친 뒤 '다시 분석'을 눌러 주세요."
            self.pending = None
            return {"status": "need_edit"}
        if field != "confirm_extraction":
            self.answers[field] = value
        p["answers"][field] = option_label
        self.log("ask", f"사용자 답변: {ASK_FIELDS[field]['label']} = {option_label}")
        if p["queue"]:  # 남은 질문이 있으면 다음 질문
            return self._question_status()
        parts = p["parts"] + [types.Part.from_function_response(
            name="ask_user", response={"answers": p["answers"]})]
        self.pending = None
        self.history.append(types.Content(role="user", parts=parts))
        return self._loop()

    def _question_status(self):
        q = self.pending["queue"][0]
        self.log("ask", f"질문: {q['question']}")
        return {"status": "need_input", **q}

    def _loop(self, max_steps=12):
        for _ in range(max_steps):
            resp, self.model = self.generate_fn(self.history, config=self.config,
                                        models=[self.model] if self.model else None)
            content = resp.candidates[0].content
            self.history.append(content)
            calls = resp.function_calls or []
            if not calls:
                self.final_text = self.verify_answer(resp.text or "")
                self.log("result", "최종 답변 작성 완료")
                return {"status": "done"}

            parts, ask_call = [], None
            for call in calls:
                args = dict(call.args or {})
                if args.get("reason"):
                    self.log("think", args["reason"])
                if call.name == "ask_user" and ask_call is None:
                    ask_call = (call, args)
                    continue
                result = self.run_tool(call.name, args)
                parts.append(types.Part.from_function_response(name=call.name, response={"result": result}))

            if ask_call:
                call, args = ask_call
                fields = [f for f in (args.get("fields") or []) if f in ASK_FIELDS] or ["employees_5plus"]
                questions = list(args.get("questions") or [])
                queue = []
                for n, f in enumerate(dict.fromkeys(fields)):
                    question = questions[n] if n < len(questions) else ASK_FIELDS[f]["label"]
                    queue.append({"field": f, "question": question,
                                  "options": list(ASK_FIELDS[f]["options"].keys())})
                self.pending = {"parts": parts, "queue": queue, "answers": {}}
                return self._question_status()

            self.history.append(types.Content(role="user", parts=parts))
        self.log("error", "단계 수 제한에 도달해 멈췄어요")
        return {"status": "error"}

    # ---------- 도구 ----------
    def run_tool(self, name, args):
        try:
            if name == "make_plan":
                self.plan = args.get("steps", [])
                self.log("plan", "실행 계획 수립", self.plan)
                return {"ok": True}
            if name == "extract_payslip":
                return self.tool_extract()
            if name == "calculate_wage":
                return self.tool_calculate()
            if name == "search_law":
                found = search_law(args.get("query", ""))
                self.retrieved_law_ids |= {f["id"] for f in found}
                self.log("tool", f"법령 검색: {args.get('query')}", [f["id"] for f in found])
                return found
            if name == "find_support_center":
                self.centers = find_support_center(args.get("region", ""))
                self.log("tool", "상담기관 검색", [c["name"] for c in self.centers])
                return self.centers
            return {"error": f"알 수 없는 도구 {name}"}
        except Exception as e:
            self.log("error", f"{name} 실행 오류", str(e))
            return {"error": "도구 실행 중 오류가 발생했어요. 사용자에게 다시 시도해 달라고 안내하세요."}

    def tool_extract(self):
        if self.extracted is None:
            for attempt in (1, 2):
                try:
                    self.extracted, _ = self.extract_fn(self.image_bytes, self.mime_type)
                    break
                except Exception as e:
                    if attempt == 1:
                        self.log("retry", "명세서 인식 실패 → 1회 재시도", str(e))
                    else:
                        raise
        issues = validate_extraction(self.extracted)
        self.log("tool", "명세서 인식 (Gemini Vision)", self.extracted.model_dump(exclude_none=True))
        if issues:
            self.log("verify", "검산 불일치 → 사용자 확인 필요", issues)
        else:
            self.log("verify", "검산 통과: 지급총액·공제총액·실수령액 일치")
        return {"data": self.extracted.model_dump(), "validation_issues": issues}

    def build_input(self):
        d, a = self.extracted, self.answers
        pay_type = a.get("pay_type") or d.pay_type
        weekly = a.get("weekly_contract_hours")
        if weekly is None and d.regular_hours:
            # 소정근로시간으로 주 소정시간 추정 (시급제: 주휴 제외 / 월급제: 주휴 포함 209시간 기준)
            est = d.regular_hours / WEEKS_PER_MONTH
            if pay_type == "monthly":
                est = est * 40 / 48
            weekly = round(est)
            if "weekly_contract_hours" not in self.inferred:
                self.inferred["weekly_contract_hours"] = weekly
                self.log("think", f"소정근로 {d.regular_hours:g}시간 → 주 {weekly}시간으로 추정")
        inp = WageInput(
            pay_type=pay_type,
            employees_5plus=a.get("employees_5plus"),
            weekly_contract_hours=weekly,
            hourly_wage=d.hourly_wage or 0,
            base_pay=d.base_pay or 0,
            fixed_allowances=d.other_allowances or 0,
            regular_hours=d.regular_hours if pay_type == "hourly" else None,
            overtime_hours=d.overtime_hours or 0,
            night_hours=d.night_hours or 0,
            holiday_hours_within_8=d.holiday_hours or 0,
            paid_weekly_holiday=d.weekly_holiday_pay or 0,
            paid_overtime=d.overtime_pay or 0,
            paid_night=d.night_pay or 0,
            paid_holiday=d.holiday_pay or 0,
            housing_deduction=d.housing_deduction or 0,
            housing_type=a.get("housing_type", "none"),
            housing_consent=a.get("housing_consent", True),
        )
        extra_missing = []
        if inp.housing_deduction > 0:
            if "housing_consent" not in a:
                extra_missing.append("housing_consent")
            elif a["housing_consent"] and "housing_type" not in a:
                extra_missing.append("housing_type")
        return inp, extra_missing

    def tool_calculate(self):
        if self.extracted is None:
            return {"error": "먼저 extract_payslip을 호출하세요."}
        inp, extra = self.build_input()
        res = calculate(inp)
        key_by_label = {label: key for key, label in REQUIRED.items()}
        missing = [key_by_label.get(m, m) for m in res.missing] + extra
        if missing:
            labels = [ASK_FIELDS[m]["label"] for m in missing if m in ASK_FIELDS]
            self.log("verify", "필수 정보 부족 → 계산 보류 (추측하지 않음)", labels)
            return {"status": "missing", "ask_fields": missing, "inferred": self.inferred}
        self.result = res
        for s in res.skipped:
            self.log("think", s)
        self.log("tool", "임금 계산 엔진 실행 (코드 계산)",
                 [f"{i.name}: 미지급 {i.shortfall:,}원" for i in res.items if i.violated] or ["위반 없음"])
        return {"status": "ok", "inferred": self.inferred, "total_shortfall": res.total_shortfall,
                "items": [{"name": i.name, "expected": i.expected, "paid": i.paid, "shortfall": i.shortfall,
                           "violated": i.violated, "formula": i.formula, "law": i.law} for i in res.items],
                "skipped_checks": res.skipped}

    # ---------- 할루시네이션 방지: 최종 답변 검증 ----------
    def verify_answer(self, text: str) -> str:
        allowed = set()
        if self.result:
            r = self.result
            allowed |= {r.total_shortfall, r.min_hourly, r.ordinary_hourly}
            for i in r.items:
                allowed |= {i.expected, i.paid, i.shortfall}
        if self.extracted:
            allowed |= {v for v in self.extracted.model_dump().values() if isinstance(v, (int, float))}
        allowed = {int(x) for x in allowed if x}
        allowed |= {10320, 2156880, 1350}

        # 인용 가능한 조문 = 검색된 조문 + 계산 엔진이 근거로 준 조문
        allowed_laws = set(self.retrieved_law_ids)
        if self.result:
            for i in self.result.items:
                allowed_laws |= set(re.findall(r"(?:근로기준법|최저임금법)\s*제\d+조", i.law))
        allowed_laws = {x.replace(" ", "") for x in allowed_laws}

        removed = []
        out_lines = []
        for line in text.split("\n"):
            bad = False
            for m in re.findall(r"\d{1,3}(?:,\d{3})+|\d{5,}", line):
                if int(m.replace(",", "")) not in allowed:
                    bad = True
                    removed.append(f"금액 {m}")
            for m in re.findall(r"(?:근로기준법|최저임금법)\s*제\s*\d+\s*조", line):
                norm = re.sub(r"\s+", " ", m).replace("제 ", "제").replace(" 조", "조")
                if norm.replace(" ", "") not in allowed_laws:
                    bad = True
                    removed.append(f"조문 {m}")
            out_lines.append("(검증되지 않은 내용이라 삭제했어요)" if bad else line)
        if removed:
            self.log("verify", "답변 검증: 계산 결과·검색 결과에 없는 내용 삭제", removed)
        else:
            self.log("verify", "답변 검증 통과: 모든 금액·조문이 계산 결과와 검색 결과에 있음")
        return "\n".join(out_lines)


# ---------- CLI 테스트 ----------
if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "samples/T10.png"
    lang = sys.argv[2] if len(sys.argv) > 2 else "ko"
    agent = WageAgent(open(path, "rb").read(), language=lang)
    shown = 0

    def show_trace():
        global shown
        for t in agent.trace[shown:]:
            print(f"{t['icon']} {t['title']}")
            if t["detail"] and t["kind"] != "tool" or t["kind"] == "plan":
                print("     ", t["detail"])
        shown = len(agent.trace)

    status = agent.start()
    while True:
        show_trace()
        if status["status"] != "need_input":
            break
        print(f"\n❓ {status['question']}")
        for n, opt in enumerate(status["options"], 1):
            print(f"   {n}. {opt}")
        choice = int(input("번호 선택 > ")) - 1
        status = agent.answer(status["options"][choice])

    if agent.result:
        print(f"\n💰 미지급 총액(코드 계산): {agent.result.total_shortfall:,}원")
    print("\n" + "=" * 60 + "\n" + (agent.final_text or ""))
