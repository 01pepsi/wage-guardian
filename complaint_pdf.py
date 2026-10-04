"""
임금체불 진정서 초안 PDF (complaint_pdf.py)
- 금액은 계산 엔진 결과(WageResult)만 사용
- 한글 폰트: Windows 맑은 고딕 → 리눅스 Noto → 없으면 reportlab 내장 한글 CID 폰트
"""
import io
from datetime import date
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONT_FILES = ["C:/Windows/Fonts/malgun.ttf",
              "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
              str(Path(__file__).parent / "fonts" / "NanumGothic.ttf")]


def _font():
    for p in FONT_FILES:
        if Path(p).exists():
            try:
                pdfmetrics.registerFont(TTFont("KR", p))
                return "KR"
            except Exception:
                pass
    pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))
    return "HYGothic-Medium"


def build_complaint_pdf(extracted, result, centers=None) -> bytes:
    font = _font()
    st = lambda size=10, lead=None, **kw: ParagraphStyle("s", fontName=font, fontSize=size,
                                                          leading=lead or size * 1.5, **kw)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm)
    e = extracted
    violated = [i for i in result.items if i.violated]
    s = []
    s.append(Paragraph("※ 이 문서는 AI가 작성한 초안입니다. 제출 전 내용을 반드시 확인·수정하세요.",
                       st(9, textColor=colors.red)))
    s.append(Spacer(1, 4 * mm))
    s.append(Paragraph("임금체불 진정서 (초안)", st(20, alignment=1)))
    s.append(Spacer(1, 6 * mm))

    def kv_table(title, rows):
        s.append(Paragraph(title, st(12)))
        t = Table([[Paragraph(k, st()), Paragraph(v or "(직접 기재)", st())] for k, v in rows],
                  colWidths=[40 * mm, 134 * mm])
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                               ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke)]))
        s.extend([t, Spacer(1, 5 * mm)])

    kv_table("1. 진정인 (근로자)", [("성명", e.worker_name), ("국적", e.nationality),
                                   ("연락처", ""), ("외국인등록번호", "")])
    kv_table("2. 피진정인 (사업장)", [("사업장명", e.workplace_name), ("소재지", e.workplace_address),
                                    ("대표자", "")])
    s.append(Paragraph("3. 진정 취지", st(12)))
    s.append(Paragraph(f"진정인은 {e.pay_month or ''} 임금 중 아래 금액 합계 <b>{result.total_shortfall:,}원</b>을 "
                       "지급받지 못하였으므로, 이를 지급받을 수 있도록 조치하여 주시기 바랍니다.", st()))
    s.append(Spacer(1, 5 * mm))
    s.append(Paragraph("4. 미지급 내역 (계산 근거 포함)", st(12)))
    rows = [[Paragraph(h, st(9)) for h in ("항목", "받아야 할 금액", "받은 금액", "미지급액", "근거", "계산식")]]
    for i in violated:
        rows.append([Paragraph(x, st(8.5)) for x in
                     (i.name, f"{i.expected:,}원", f"{i.paid:,}원", f"{i.shortfall:,}원", i.law, i.formula)])
    rows.append([Paragraph("합계", st(9)), "", "", Paragraph(f"{result.total_shortfall:,}원", st(9)), "", ""])
    t = Table(rows, colWidths=[28 * mm, 24 * mm, 22 * mm, 22 * mm, 34 * mm, 44 * mm], repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    s.extend([t, Spacer(1, 5 * mm)])
    s.append(Paragraph("5. 첨부 자료", st(12)))
    s.append(Paragraph("① 급여명세서 사본  ② 근로계약서 사본  ③ 출퇴근 기록(있는 경우)", st()))
    s.append(Spacer(1, 5 * mm))
    if centers:
        s.append(Paragraph("6. 제출·상담처", st(12)))
        for c in centers:
            s.append(Paragraph(f"· {c['name']} — {c['how']}", st()))
        s.append(Spacer(1, 5 * mm))
    s.append(Paragraph(f"작성일: {date.today():%Y년 %m월 %d일}", st(alignment=2)))
    s.append(Paragraph("진정인: ____________________ (서명)", st(alignment=2)))
    doc.build(s)
    return buf.getvalue()


if __name__ == "__main__":
    from demo import SAMPLE_EXTRACTIONS
    from extractor import PayslipData
    from wage_calc import WageInput, calculate
    e = PayslipData(**SAMPLE_EXTRACTIONS["T10"])
    r = calculate(WageInput(pay_type="hourly", employees_5plus=True, weekly_contract_hours=40, hourly_wage=10000,
                            regular_hours=174, overtime_hours=15, paid_overtime=150000, night_hours=20,
                            housing_deduction=400000, housing_consent=False))
    Path("sample_complaint.pdf").write_bytes(build_complaint_pdf(e, r))
    print("sample_complaint.pdf 생성")
