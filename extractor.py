"""
급여명세서 인식 + 검산 (extractor.py)
- extract_payslip(): Gemini Vision으로 사진에서 항목을 JSON으로 추출
- validate_extraction(): 합계를 코드로 검산 (할루시네이션 방지 1단계)
단독 실행: py extractor.py samples/T10.png
"""
import json
import sys
from typing import Optional, List
from pydantic import BaseModel, Field
from google.genai import types
from llm import generate


class PayslipData(BaseModel):
    worker_name: Optional[str] = None
    nationality: Optional[str] = None
    workplace_name: Optional[str] = None
    workplace_address: Optional[str] = None
    pay_month: Optional[str] = Field(None, description="지급 대상 월, 예: 2026-09")
    pay_type: Optional[str] = Field(None, description="'hourly'(시급제) 또는 'monthly'(월급제). 명세서에 시급이 적혀 있으면 hourly")
    hourly_wage: Optional[int] = Field(None, description="시급(원)")
    regular_hours: Optional[float] = Field(None, description="소정(기본) 근로시간 합계")
    overtime_hours: Optional[float] = None
    night_hours: Optional[float] = None
    holiday_hours: Optional[float] = None
    base_pay: Optional[int] = Field(None, description="기본급(원)")
    weekly_holiday_pay: Optional[int] = Field(None, description="주휴수당(원). 항목이 없으면 0")
    overtime_pay: Optional[int] = Field(None, description="연장근로수당(원). 항목이 없으면 0")
    night_pay: Optional[int] = Field(None, description="야간근로수당(원). 항목이 없으면 0")
    holiday_pay: Optional[int] = Field(None, description="휴일근로수당(원). 항목이 없으면 0")
    other_allowances: Optional[int] = Field(None, description="그 밖의 지급 항목 합계(원). 없으면 0")
    gross_total: Optional[int] = Field(None, description="지급총액(원)")
    housing_deduction: Optional[int] = Field(None, description="숙식비/기숙사비 공제(원). 없으면 0")
    other_deductions: Optional[int] = Field(None, description="세금·4대보험 등 그 밖의 공제 합계(원)")
    deductions_total: Optional[int] = Field(None, description="공제총액(원)")
    net_pay: Optional[int] = Field(None, description="실수령액(원)")
    low_confidence_fields: List[str] = Field(default_factory=list,
        description="흐리거나 잘려서 확실하게 읽지 못한 필드 이름 목록")


PROMPT = """너는 한국 급여명세서를 읽는 OCR 도우미다.
이미지에 실제로 보이는 값만 정해진 JSON 형식으로 옮겨 적어라.
규칙:
- 금액은 쉼표 없는 정수(원)로 적는다.
- 보이지 않거나 읽을 수 없는 값은 추측하지 말고 null로 둔다.
- 명세서에 항목 자체가 없는 수당·공제는 0으로 적는다.
- 숫자가 흐리거나 잘려서 확실하지 않으면 그 필드 이름을 low_confidence_fields에 넣는다.
- 계산하거나 값을 고치지 말고, 적힌 그대로 옮긴다."""


def extract_payslip(image_bytes: bytes, mime_type: str = "image/png"):
    """사진 → (PayslipData, 사용한 모델 이름)"""
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=PayslipData,
        temperature=0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    contents = [types.Part.from_bytes(data=image_bytes, mime_type=mime_type), PROMPT]
    resp, model = generate(contents, config=config)
    data = resp.parsed if resp.parsed is not None else PayslipData.model_validate_json(resp.text)
    return data, model


def validate_extraction(d: PayslipData, tolerance: int = 10):
    """합계 검산. 문제 목록을 돌려준다 (빈 목록이면 통과)."""
    issues = []
    v = lambda x: x or 0
    pay_items = v(d.base_pay) + v(d.weekly_holiday_pay) + v(d.overtime_pay) + v(d.night_pay) + v(d.holiday_pay) + v(d.other_allowances)
    if d.gross_total is None:
        issues.append("지급총액을 읽지 못했어요.")
    elif abs(pay_items - d.gross_total) > tolerance:
        issues.append(f"지급 항목 합계 {pay_items:,}원과 지급총액 {d.gross_total:,}원이 달라요.")

    ded_items = v(d.housing_deduction) + v(d.other_deductions)
    if d.deductions_total is not None and abs(ded_items - d.deductions_total) > tolerance:
        issues.append(f"공제 항목 합계 {ded_items:,}원과 공제총액 {d.deductions_total:,}원이 달라요.")

    if None not in (d.gross_total, d.deductions_total, d.net_pay):
        if abs(d.gross_total - d.deductions_total - d.net_pay) > tolerance:
            issues.append(f"지급총액 - 공제총액({d.gross_total - d.deductions_total:,}원)이 실수령액 {d.net_pay:,}원과 달라요.")

    if d.pay_type == "hourly" and d.hourly_wage is None:
        issues.append("시급제인데 시급을 읽지 못했어요.")
    if d.low_confidence_fields:
        issues.append("흐리게 읽힌 항목: " + ", ".join(d.low_confidence_fields))
    return issues


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "samples/T10.png"
    with open(path, "rb") as f:
        data, model = extract_payslip(f.read())
    print(f"[사용 모델] {model}")
    print(json.dumps(data.model_dump(), ensure_ascii=False, indent=2))
    problems = validate_extraction(data)
    print("[검산]", "통과 ✅" if not problems else problems)
