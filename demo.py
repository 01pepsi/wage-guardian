"""
데모 모드 (demo.py) — Gemini를 부르지 않고 Agent 흐름을 재현
- 용도: 무료 사용량 초과·네트워크 오류 시 대체 경로(Fallback), 화면 개발·시연 백업
- 사진 인식: 샘플 명세서의 저장된 인식 결과 사용
- AI 판단: 정해진 규칙으로 도구 호출 순서를 흉내냄 (계산·검산·법령·검증은 실제 코드가 그대로 실행)
※ 화면에 '데모 모드'임을 항상 표시한다.
"""
from google.genai import types
from extractor import PayslipData
from agent import ASK_FIELDS

BASE = dict(workplace_name=None, pay_month="2026-09", holiday_hours=0, weekly_holiday_pay=0, overtime_pay=0,
            night_pay=0, holiday_pay=0, other_allowances=0, housing_deduction=0, low_confidence_fields=[])

SAMPLE_EXTRACTIONS = {
    "T10": dict(BASE, worker_name="NGUYEN VAN AN", nationality="베트남", workplace_name="(가상) 한빛조선협력 주식회사",
                workplace_address="경상남도 거제시 (가상주소)", pay_type="hourly", hourly_wage=10000, regular_hours=174,
                overtime_hours=15, night_hours=20, base_pay=1740000, overtime_pay=150000, gross_total=1890000,
                housing_deduction=400000, other_deductions=150000, deductions_total=550000, net_pay=1340000),
    "G01_mismatch": dict(BASE, worker_name="NGUYEN VAN AN", nationality="베트남", workplace_name="(가상) 한빛조선협력 주식회사",
                workplace_address="경상남도 거제시 (가상주소)", pay_type="hourly", hourly_wage=10000, regular_hours=174,
                overtime_hours=15, night_hours=20, base_pay=1740000, overtime_pay=150000, gross_total=1990000,
                housing_deduction=400000, other_deductions=150000, deductions_total=550000, net_pay=1440000),
    "T03": dict(BASE, worker_name="RAJ KUMAR THAPA", nationality="네팔", workplace_name="(가상) 진해정밀 주식회사",
                workplace_address="경상남도 창원시 진해구 (가상주소)", pay_type="monthly", regular_hours=209,
                overtime_hours=20, night_hours=0, base_pay=2156880, gross_total=2156880,
                other_deductions=190000, deductions_total=190000, net_pay=1966880),
    "T07": dict(BASE, worker_name="SITI RAHAYU", nationality="인도네시아", workplace_name="(가상) 밀양들녘농업법인",
                workplace_address="경상남도 밀양시 (가상주소)", pay_type="monthly", regular_hours=209,
                overtime_hours=0, night_hours=0, base_pay=2156880, gross_total=2156880, housing_deduction=600000,
                other_deductions=190000, deductions_total=790000, net_pay=1366880),
    "T01": dict(BASE, worker_name="SOK DARA", nationality="캄보디아", workplace_name="(가상) 김해부품 주식회사",
                workplace_address="경상남도 김해시 (가상주소)", pay_type="monthly", regular_hours=209,
                overtime_hours=10, night_hours=0, base_pay=2156880, overtime_pay=154800, gross_total=2311680,
                other_deductions=205000, deductions_total=205000, net_pay=2106680),
}


def demo_extract_fn(sample_key):
    def _extract(image_bytes, mime_type="image/png"):
        if sample_key not in SAMPLE_EXTRACTIONS:
            raise RuntimeError("데모 모드는 샘플 명세서만 지원해요. 직접 올린 사진은 일반 모드에서 분석하세요.")
        return PayslipData(**SAMPLE_EXTRACTIONS[sample_key]), "demo"
    return _extract


class _Resp:
    def __init__(self, calls=None, text=None):
        calls = calls or []
        parts = [types.Part.from_function_call(name=n, args=a) for n, a in calls] or [types.Part(text=text)]
        self.candidates = [types.Candidate(content=types.Content(role="model", parts=parts))]
        self.function_calls = [types.FunctionCall(name=n, args=a) for n, a in calls] or None
        self.text = text


LAW_QUERY = {"min_wage": "최저임금법 제6조 최저임금", "weekly_holiday": "근로기준법 제55조 주휴수당",
             "overtime": "근로기준법 제56조 연장근로 가산", "night": "근로기준법 제56조 야간근로 가산",
             "holiday": "근로기준법 제56조 휴일근로", "housing": "근로기준법 제43조 숙식비 공제 동의"}


def demo_generate_fn(agent_getter):
    """agent 상태를 보고 다음 도구 호출을 정한다 (Gemini 대신)."""
    stage = {"n": 0, "laws_done": False, "confirm_asked": False}

    def _generate(history, config=None, models=None):
        ag = agent_getter()
        if stage["n"] == 0:
            stage["n"] = 1
            return _Resp(calls=[
                ("make_plan", {"reason": "명세서 분석부터 구제 안내까지 필요한 단계를 정한다.",
                               "steps": ["명세서 인식 및 검산", "임금 계산 (부족한 정보는 질문)",
                                         "위반 항목 법령 근거 확인", "관할 노동청·상담기관 안내", "결과 설명"]}),
                ("extract_payslip", {"reason": "사진에서 금액과 근로시간을 읽고 합계를 검산한다."}),
                ("calculate_wage", {"reason": "읽은 값으로 받아야 할 임금을 계산한다."})]), "demo"
        from validators import extraction_issues
        if extraction_issues(ag) and not stage["confirm_asked"]:
            stage["confirm_asked"] = True
            return _Resp(calls=[("ask_user", {"reason": "검산이 맞지 않아 사용자 확인이 필요하다.",
                                              "fields": ["confirm_extraction"],
                                              "questions": ["명세서의 합계가 맞지 않아요. 읽은 값이 사진과 같은가요?"]})]), "demo"
        if ag.result is None:
            inp, extra = ag.build_input()
            from wage_calc import calculate, REQUIRED
            key_by_label = {l: k for k, l in REQUIRED.items()}
            missing = [key_by_label.get(m, m) for m in calculate(inp).missing] + extra
            missing = [m for m in missing if m not in ag.answers]
            if missing:
                q = {"employees_5plus": "일하는 곳의 직원(사장님 제외)이 5명 이상인가요?",
                     "housing_consent": "월급에서 숙식비를 빼는 것에 서면으로 동의했나요?",
                     "housing_type": "어떤 숙소에서 지내나요?",
                     "weekly_contract_hours": "계약서에 적힌 일주일 근로시간은 몇 시간인가요?",
                     "pay_type": "시급제인가요, 월급제인가요?"}
                return _Resp(calls=[("ask_user", {"reason": "계산에 꼭 필요한 정보라 추측하지 않고 묻는다.",
                                                  "fields": missing,
                                                  "questions": [q.get(m, ASK_FIELDS[m]["label"]) for m in missing]})]), "demo"
            return _Resp(calls=[("calculate_wage", {"reason": "사용자 답변을 반영해 다시 계산한다."})]), "demo"
        violated = [i for i in ag.result.items if i.violated]
        if not stage["laws_done"]:
            stage["laws_done"] = True
            calls = [("search_law", {"reason": f"{i.name}의 법적 근거를 확인한다.", "query": LAW_QUERY.get(i.code, i.name)})
                     for i in violated]
            if violated:
                calls.append(("find_support_center", {"reason": "사업장 관할 노동청과 상담기관을 찾는다.",
                                                      "region": ag.extracted.workplace_address or ""}))
                return _Resp(calls=calls), "demo"
        return _Resp(text=final_text(ag)), "demo"

    return _generate


def final_text(ag):
    r = ag.result
    violated = [i for i in r.items if i.violated]
    if not violated:
        return ("결론: 이번 달 임금은 법 기준에 맞게 지급되었어요. 받지 못한 금액이 없어요.\n\n"
                "이 결과는 참고용이며, 최종 판단은 고용노동부 또는 공인노무사에게 확인하세요.")
    lines = [f"결론: 받아야 할 임금 중 총 {r.total_shortfall:,}원을 받지 못했어요.", "", "항목별 설명:"]
    for n, i in enumerate(violated, 1):
        law = i.law.split(" 제")[0] + " 제" + i.law.split(" 제")[1].split("조")[0] + "조" if "제" in i.law else i.law
        lines.append(f"{n}. {i.name}: {i.shortfall:,}원 (근거: {law})")
        lines.append(f"   - 계산: {i.formula}")
    lines += ["", "다음에 할 일:", "- 아래 '진정서 초안 PDF'를 내려받아 내용을 확인하세요.",
              "- 고용노동부 고객상담센터(국번 없이 1350)에서 외국어로 상담할 수 있어요.", "",
              "이 결과는 참고용이며, 최종 판단은 고용노동부 또는 공인노무사에게 확인하세요."]
    return "\n".join(lines)
