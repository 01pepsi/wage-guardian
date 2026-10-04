"""
테스트용 가상 급여명세서 이미지 생성 (make_samples.py)
실행: py make_samples.py  →  samples/ 폴더에 PNG 생성
※ 모든 인물·사업장은 가상입니다.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

OUT = Path(__file__).parent / "samples"
FONT_CANDIDATES = [
    "C:/Windows/Fonts/malgun.ttf",          # Windows 맑은 고딕
    "C:/Windows/Fonts/malgunbd.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
]


def font(size):
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    raise RuntimeError("한글 폰트를 찾지 못했어요.")


SAMPLES = {
    "T10": dict(  # 복합 위반 (시연용)
        name="NGUYEN VAN AN", nation="베트남", company="(가상) 한빛조선협력 주식회사", addr="경상남도 거제시 (가상주소)",
        month="2026년 9월", rate="시급 10,000원", hours=[("소정근로시간", "174시간"), ("연장근로시간", "15시간"), ("야간근로시간", "20시간"), ("휴일근로시간", "0시간")],
        pay=[("기본급", "1,740,000", "10,000원 x 174시간"), ("연장근로수당", "150,000", "10,000원 x 15시간")],
        gross="1,890,000",
        ded=[("기숙사비(숙식비)", "400,000"), ("소득세·4대보험", "150,000")],
        ded_total="550,000", net="1,340,000"),
    "T03": dict(  # 연장수당 미지급 (월급제)
        name="RAJ KUMAR THAPA", nation="네팔", company="(가상) 진해정밀 주식회사", addr="경상남도 창원시 진해구 (가상주소)",
        month="2026년 9월", rate="월급제", hours=[("소정근로시간", "209시간"), ("연장근로시간", "20시간"), ("야간근로시간", "0시간"), ("휴일근로시간", "0시간")],
        pay=[("기본급", "2,156,880", "월 고정")],
        gross="2,156,880",
        ded=[("소득세·4대보험", "190,000")],
        ded_total="190,000", net="1,966,880"),
    "T07": dict(  # 숙식비 과다 공제
        name="SITI RAHAYU", nation="인도네시아", company="(가상) 밀양들녘농업법인", addr="경상남도 밀양시 (가상주소)",
        month="2026년 9월", rate="월급제", hours=[("소정근로시간", "209시간"), ("연장근로시간", "0시간"), ("야간근로시간", "0시간"), ("휴일근로시간", "0시간")],
        pay=[("기본급", "2,156,880", "월 고정")],
        gross="2,156,880",
        ded=[("숙식비", "600,000"), ("소득세·4대보험", "190,000")],
        ded_total="790,000", net="1,366,880"),
    "T01": dict(  # 정상 지급
        name="SOK DARA", nation="캄보디아", company="(가상) 김해부품 주식회사", addr="경상남도 김해시 (가상주소)",
        month="2026년 9월", rate="월급제", hours=[("소정근로시간", "209시간"), ("연장근로시간", "10시간"), ("야간근로시간", "0시간"), ("휴일근로시간", "0시간")],
        pay=[("기본급", "2,156,880", "월 고정"), ("연장근로수당", "154,800", "10,320원 x 10시간 x 1.5")],
        gross="2,311,680",
        ded=[("소득세·4대보험", "205,000")],
        ded_total="205,000", net="2,106,680"),
}
# G01: 지급총액을 일부러 틀리게 (검산 테스트용)
SAMPLES["G01_mismatch"] = dict(SAMPLES["T10"], gross="1,990,000", net="1,440,000")


def render(d):
    W, H = 900, 1100
    img = Image.new("RGB", (W, H), "white")
    g = ImageDraw.Draw(img)
    f_title, f, f_small = font(40), font(24), font(18)
    g.text((W // 2, 50), "급 여 명 세 서", font=f_title, fill="black", anchor="mm")
    g.text((W // 2, 95), f"{d['month']}분", font=f, fill="black", anchor="mm")
    y = 140
    for k, v in [("성명", d["name"]), ("국적", d["nation"]), ("사업장", d["company"]), ("주소", d["addr"]), ("임금형태", d["rate"])]:
        g.text((60, y), f"{k} : {v}", font=f, fill="black"); y += 38
    y += 10
    g.text((60, y), "■ 근로시간", font=f, fill="black"); y += 36
    g.text((80, y), "   ".join(f"{k} {v}" for k, v in d["hours"][:2]), font=f_small, fill="black"); y += 28
    g.text((80, y), "   ".join(f"{k} {v}" for k, v in d["hours"][2:]), font=f_small, fill="black"); y += 45

    def table(title, rows, total_label, total, with_formula):
        nonlocal y
        g.text((60, y), title, font=f, fill="black"); y += 38
        g.line((60, y, W - 60, y), fill="black", width=2); y += 10
        for r in rows:
            g.text((80, y), r[0], font=f, fill="black")
            g.text((W - 80, y), f"{r[1]} 원", font=f, fill="black", anchor="ra")
            if with_formula and len(r) > 2:
                g.text((330, y + 4), f"({r[2]})", font=f_small, fill="#555555")
            y += 38
        g.line((60, y, W - 60, y), fill="black", width=1); y += 10
        g.text((80, y), total_label, font=f, fill="black")
        g.text((W - 80, y), f"{total} 원", font=f, fill="black", anchor="ra"); y += 55

    table("■ 지급 내역", d["pay"], "지급총액", d["gross"], True)
    table("■ 공제 내역", d["ded"], "공제총액", d["ded_total"], False)
    g.rectangle((60, y, W - 60, y + 60), outline="black", width=3)
    g.text((80, y + 15), "실수령액", font=f, fill="black")
    g.text((W - 80, y + 15), f"{d['net']} 원", font=f, fill="black", anchor="ra")
    g.text((W // 2, H - 40), "※ 경진대회 테스트용 가상 명세서 (실존 인물·사업장 아님)", font=f_small, fill="#888888", anchor="mm")
    return img


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for key, d in SAMPLES.items():
        render(d).save(OUT / f"{key}.png")
        print("생성:", OUT / f"{key}.png")
    # T08: 흐린 사진 (T10을 흐리게 + 회전)
    blurred = render(SAMPLES["T10"]).filter(ImageFilter.GaussianBlur(3.2)).rotate(2, fillcolor="white")
    blurred.save(OUT / "T08_blurry.png")
    print("생성:", OUT / "T08_blurry.png")