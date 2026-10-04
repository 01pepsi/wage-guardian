"""
임금 계산 엔진 (wage_calc.py)
- 금액 계산은 이 파일에서만 한다. LLM은 계산하지 않는다.
- 규칙 값은 rules_2026.json 에서 읽는다.
"""
import json
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path

RULES_PATH = Path(__file__).parent / "rules_2026.json"
WEEKS_PER_MONTH = 365 / 7 / 12  # 약 4.345주

LAW = {
    "min_wage": "최저임금법 제6조",
    "weekly_holiday": "근로기준법 제55조",
    "overtime": "근로기준법 제56조 제1항",
    "night": "근로기준법 제56조 제3항",
    "holiday": "근로기준법 제56조 제2항",
    "deduction": "근로기준법 제43조 (임금 전액 지급)",
    "small_business": "근로기준법 제11조, 시행령 별표1",
}


def load_rules(path=RULES_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def won(x):
    """원 단위 반올림"""
    return int(math.floor(x + 0.5))


@dataclass
class WageInput:
    # 필수 (없으면 계산 거부)
    pay_type: str = None                 # "hourly"(시급제) 또는 "monthly"(월급제)
    employees_5plus: bool = None         # 상시근로자 5인 이상 여부
    weekly_contract_hours: float = None  # 주 소정근로시간 (예: 40)
    # 계약 조건
    hourly_wage: int = 0                 # 시급제: 계약 시급
    base_pay: int = 0                    # 월급제: 기본급(주휴 포함)
    fixed_allowances: int = 0            # 매월 고정 수당
    monthly_bonus: int = 0               # 매월 지급 정기상여
    welfare_cash: int = 0                # 매월 현금성 복리후생비(식대 등)
    regular_hours: float = None          # 시급제: 이번 달 소정근로시간 (없으면 주 소정 x 4.345)
    weekly_holiday_eligible: bool = True # 주휴 요건(개근) 충족 여부
    probation: bool = False              # 수습 3개월 이내 + 1년 이상 계약
    simple_labor: bool = False           # 단순노무직(수습 감액 불가)
    # 이번 달 추가 근로시간
    overtime_hours: float = 0
    night_hours: float = 0
    holiday_hours_within_8: float = 0
    holiday_hours_over_8: float = 0
    # 실제 지급액
    paid_base: int = 0                   # 시급제: 실제 지급 기본급 (월급제는 base_pay 사용)
    paid_weekly_holiday: int = 0
    paid_overtime: int = 0
    paid_night: int = 0
    paid_holiday: int = 0
    # 숙식비
    housing_type: str = "none"           # none / house_with_meals / temporary_with_meals / house_only / temporary_only
    housing_deduction: int = 0
    housing_consent: bool = True         # 숙식비 공제 서면 동의 여부


@dataclass
class Item:
    code: str
    name: str
    expected: int
    paid: int
    shortfall: int
    violated: bool
    formula: str
    law: str


@dataclass
class WageResult:
    ok: bool
    missing: list = field(default_factory=list)
    items: list = field(default_factory=list)
    skipped: list = field(default_factory=list)   # Agent 판단 근거(생략한 검사와 이유)
    total_shortfall: int = 0
    min_hourly: int = 0
    ordinary_hourly: int = 0
    monthly_standard_hours: int = 0

    def to_dict(self):
        return asdict(self)


REQUIRED = {
    "pay_type": "임금 형태(시급제/월급제)",
    "employees_5plus": "사업장 상시근로자 5인 이상 여부",
    "weekly_contract_hours": "주 소정근로시간",
}


def calculate(inp: WageInput, rules=None) -> WageResult:
    rules = rules or load_rules()

    # 1) 필수값 검증: 없으면 추측하지 않고 계산 거부
    missing = [label for key, label in REQUIRED.items() if getattr(inp, key) is None]
    if missing:
        return WageResult(ok=False, missing=missing)

    res = WageResult(ok=True)
    items, skipped = [], []

    # 2) 최저시급 (수습 감액)
    min_hourly = rules["min_hourly_wage"]
    if inp.probation and not inp.simple_labor:
        min_hourly = won(min_hourly * rules["probation_rate"])

    # 3) 주휴시간과 월 소정근로시간(주휴 포함)
    weekly = inp.weekly_contract_hours
    holiday_hours_week = 0
    if weekly >= rules["weekly_holiday_min_hours"] and inp.weekly_holiday_eligible:
        holiday_hours_week = min(8, weekly / 40 * 8)
    else:
        skipped.append("주휴수당: 주 15시간 미만이거나 개근 요건 미충족으로 검사 생략")
    monthly_std_hours = won((weekly + holiday_hours_week) * WEEKS_PER_MONTH)

    if inp.pay_type == "hourly":
        regular_hours = inp.regular_hours if inp.regular_hours is not None else weekly * WEEKS_PER_MONTH
        # 최저임금
        if inp.hourly_wage < min_hourly:
            short = won((min_hourly - inp.hourly_wage) * regular_hours)
            items.append(Item("min_wage", "최저임금 미달", won(min_hourly * regular_hours),
                              won(inp.hourly_wage * regular_hours), short, True,
                              f"({min_hourly:,} - {inp.hourly_wage:,})원 x {regular_hours:.1f}시간", LAW["min_wage"]))
        else:
            items.append(Item("min_wage", "최저임금", 0, 0, 0, False,
                              f"시급 {inp.hourly_wage:,}원 >= 최저시급 {min_hourly:,}원", LAW["min_wage"]))
        ordinary_hourly = max(inp.hourly_wage, min_hourly)
        # 주휴수당 (시급제만 별도 확인)
        if holiday_hours_week > 0:
            exp = won(ordinary_hourly * holiday_hours_week * WEEKS_PER_MONTH)
            short = max(0, exp - inp.paid_weekly_holiday)
            items.append(Item("weekly_holiday", "주휴수당", exp, inp.paid_weekly_holiday, short, short > 0,
                              f"{ordinary_hourly:,}원 x {holiday_hours_week:g}시간 x {WEEKS_PER_MONTH:.3f}주",
                              LAW["weekly_holiday"]))
    else:  # monthly
        included = inp.base_pay + inp.fixed_allowances + inp.monthly_bonus + inp.welfare_cash
        required = min_hourly * monthly_std_hours
        short = max(0, required - included)
        items.append(Item("min_wage", "최저임금" + (" 미달" if short else ""), required, included, short, short > 0,
                          f"최저시급 {min_hourly:,}원 x 월 {monthly_std_hours}시간 = {required:,}원 vs 산입임금 {included:,}원",
                          LAW["min_wage"]))
        ordinary_hourly = max(won((inp.base_pay + inp.fixed_allowances) / monthly_std_hours), min_hourly)
        skipped.append("주휴수당: 월급제는 기본급에 포함된 것으로 보고 최저임금 비교에 반영")

    # 4) 연장·야간·휴일 (5인 미만이면 가산 미적용, 일한 시간의 기본 임금은 지급 대상)
    big = inp.employees_5plus
    if not big:
        skipped.append("연장·야간·휴일 가산수당: 상시근로자 5인 미만 사업장이라 가산율 미적용 (일한 시간의 기본 임금만 계산)")

    if inp.overtime_hours:
        rate = 1 + (rules["overtime_premium"] if big else 0)
        exp = won(ordinary_hourly * inp.overtime_hours * rate)
        short = max(0, exp - inp.paid_overtime)
        items.append(Item("overtime", "연장근로수당", exp, inp.paid_overtime, short, short > 0,
                          f"{ordinary_hourly:,}원 x {inp.overtime_hours:g}시간 x {rate:g}배",
                          LAW["overtime"] if big else LAW["small_business"]))

    if inp.night_hours and big:
        exp = won(ordinary_hourly * inp.night_hours * rules["night_premium"])
        short = max(0, exp - inp.paid_night)
        items.append(Item("night", "야간근로 가산수당", exp, inp.paid_night, short, short > 0,
                          f"{ordinary_hourly:,}원 x {inp.night_hours:g}시간 x {rules['night_premium']:g}",
                          LAW["night"]))

    if inp.holiday_hours_within_8 or inp.holiday_hours_over_8:
        r1 = 1 + (rules["holiday_premium_within_8h"] if big else 0)
        r2 = 1 + (rules["holiday_premium_over_8h"] if big else 0)
        exp = won(ordinary_hourly * (inp.holiday_hours_within_8 * r1 + inp.holiday_hours_over_8 * r2))
        short = max(0, exp - inp.paid_holiday)
        items.append(Item("holiday", "휴일근로수당", exp, inp.paid_holiday, short, short > 0,
                          f"{ordinary_hourly:,}원 x ({inp.holiday_hours_within_8:g}시간 x {r1:g} + {inp.holiday_hours_over_8:g}시간 x {r2:g})",
                          LAW["holiday"] if big else LAW["small_business"]))

    # 5) 숙식비 공제
    if inp.housing_deduction > 0:
        if not inp.housing_consent:
            items.append(Item("housing", "숙식비 공제 (서면 동의 없음)", 0, inp.housing_deduction,
                              inp.housing_deduction, True,
                              f"서면 동의 없는 공제 {inp.housing_deduction:,}원 전액", LAW["deduction"]))
        else:
            cap_rate = rules["housing_deduction_caps"].get(inp.housing_type)
            if cap_rate is None:
                skipped.append("숙식비: 숙소 형태 정보가 없어 상한 검사 생략")
            else:
                monthly_ordinary = ordinary_hourly * monthly_std_hours
                cap = won(monthly_ordinary * cap_rate)
                short = max(0, inp.housing_deduction - cap)
                items.append(Item("housing", "숙식비 공제 한도", cap, inp.housing_deduction, short, short > 0,
                                  f"월 통상임금 {monthly_ordinary:,}원 x {cap_rate:.0%} = 상한 {cap:,}원",
                                  "고용노동부 외국인근로자 숙식비 지침"))
    elif inp.housing_type == "none":
        skipped.append("숙식비: 공제 내역이 없어 검사 생략")

    res.items = items
    res.skipped = skipped
    res.total_shortfall = sum(i.shortfall for i in items)
    res.min_hourly = min_hourly
    res.ordinary_hourly = ordinary_hourly
    res.monthly_standard_hours = monthly_std_hours
    return res