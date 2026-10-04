"""
임금 지킴이 웹 화면 (app.py)
실행: py -m streamlit run app.py
"""
import json
from pathlib import Path
import pandas as pd
import streamlit as st

import llm
from agent import WageAgent, LANG_NAMES
from extractor import PayslipData
from complaint_pdf import build_complaint_pdf
from demo import demo_generate_fn, demo_extract_fn, SAMPLE_EXTRACTIONS

st.set_page_config(page_title="임금 지킴이 Wage Guardian", page_icon="🛡️", layout="wide")

# 브라우저 자동 번역이 한국어 화면을 엉뚱하게 바꾸지 않도록 페이지 언어를 한국어로 지정
import streamlit.components.v1 as components
components.html("""<script>
const d = window.parent.document;
d.documentElement.lang = 'ko';
d.documentElement.setAttribute('translate', 'no');
if (!d.querySelector('meta[name=google]')) {
  const m = d.createElement('meta'); m.name = 'google'; m.content = 'notranslate'; d.head.appendChild(m);
}
</script>""", height=0)
SAMPLES_DIR = Path(__file__).parent / "samples"
SAMPLE_LABELS = {"T10": "복합 위반 (시연용)", "T03": "연장수당 미지급", "T07": "숙식비 과다 공제",
                 "T01": "정상 지급", "G01_mismatch": "합계 불일치 (검산 테스트)"}
LANG_OPTIONS = {"한국어": "ko", "Tiếng Việt": "vi", "नेपाली": "ne", "Bahasa Indonesia": "id",
                "ភាសាខ្មែរ": "km", "English": "en"}
FIELD_LABELS = {"worker_name": "성명", "nationality": "국적", "workplace_name": "사업장", "workplace_address": "주소",
                "pay_month": "지급월", "pay_type": "임금형태", "hourly_wage": "시급", "regular_hours": "소정근로시간",
                "overtime_hours": "연장시간", "night_hours": "야간시간", "holiday_hours": "휴일시간",
                "base_pay": "기본급", "weekly_holiday_pay": "주휴수당", "overtime_pay": "연장수당",
                "night_pay": "야간수당", "holiday_pay": "휴일수당", "other_allowances": "기타수당",
                "gross_total": "지급총액", "housing_deduction": "숙식비 공제", "other_deductions": "기타 공제",
                "deductions_total": "공제총액", "net_pay": "실수령액"}

ss = st.session_state
ss.setdefault("agent", None)
ss.setdefault("status", None)
ss.setdefault("image", None)
ss.setdefault("sample_key", None)
ss.setdefault("error", None)

llm.WAIT_NOTIFY = lambda s: st.toast(f"⏳ 무료 사용량 한도 → {s}초 기다렸다가 다시 시도해요")


# ---------------- 실행 도우미 ----------------
def new_agent(extracted=None):
    lang = LANG_OPTIONS[ss.lang_label]
    if ss.demo:
        holder = {}
        ag = WageAgent(ss.image or b"", language=lang, extracted=extracted,
                       extract_fn=demo_extract_fn(ss.sample_key),
                       generate_fn=demo_generate_fn(lambda: holder["a"]))
        holder["a"] = ag
        return ag
    return WageAgent(ss.image, language=lang, extracted=extracted)


def run(fn, *args):
    ss.error = None
    try:
        with st.spinner("🤖 Agent가 판단하고 도구를 실행하는 중이에요..."):
            ss.status = fn(*args)
    except Exception as e:
        msg = str(e)
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "사용 가능한" in msg:
            ss.error = "오늘 무료 AI 사용량을 모두 썼어요. 왼쪽에서 '데모 모드'를 켜면 샘플로 전체 흐름을 볼 수 있어요."
        else:
            ss.error = f"처리 중 문제가 생겼어요. 잠시 후 다시 시도해 주세요. ({msg[:150]})"
        if ss.agent:
            ss.agent.log("error", "오류 발생 → 사용자에게 안내", msg[:200])


def start_analysis(extracted=None):
    ss.agent = new_agent(extracted)
    run(ss.agent.start)


# ---------------- 사이드바 ----------------
with st.sidebar:
    st.header("🛡️ 임금 지킴이")
    st.selectbox("답변 언어 / Language", list(LANG_OPTIONS.keys()), key="lang_label")
    st.toggle("데모 모드 (AI 호출 없이 샘플 재생)", key="demo",
              help="무료 사용량 초과·네트워크 오류 시 대체 경로. 계산·검산·법령 검색은 실제 코드로 실행돼요.")
    st.divider()
    st.subheader("샘플 명세서로 체험하기")
    for key, label in SAMPLE_LABELS.items():
        if st.button(f"{key} · {label}", width="stretch"):
            ss.image = (SAMPLES_DIR / f"{key}.png").read_bytes()
            ss.sample_key = key
            ss.agent, ss.status = None, None
    st.divider()
    if ss.agent:
        st.subheader("🧠 Agent 상태 (Memory)")
        st.json({"사용 모델": ss.agent.model, "사용자 답변": ss.agent.answers, "추정값": ss.agent.inferred,
                 "검색한 조문": sorted(ss.agent.retrieved_law_ids)}, expanded=False)

# ---------------- 본문 ----------------
st.title("🛡️ 임금 지킴이 — 외국인 근로자 임금체불 확인 AI Agent")
st.caption("급여명세서 사진 한 장 → Agent가 계획·인식·계산·법령 확인·검증 → 미지급액과 진정서 초안까지")
if ss.demo:
    st.info("🎬 데모 모드: 저장된 샘플 인식 결과와 규칙 기반 흐름으로 실행해요. (계산·검산·법령·답변 검증은 실제 코드)")

up = st.file_uploader("급여명세서 사진 올리기 (PNG/JPG)", type=["png", "jpg", "jpeg"])
if up is not None and (ss.image != up.getvalue()):
    ss.image, ss.sample_key = up.getvalue(), None
    ss.agent, ss.status = None, None

left, right = st.columns([3, 2], gap="large")

with left:
    if ss.image:
        with st.expander("📄 올린 명세서", expanded=ss.agent is None):
            st.image(ss.image, width=420)
        if ss.agent is None and st.button("🔍 분석 시작", type="primary", width="stretch"):
            start_analysis()
            st.rerun()
    else:
        st.write("👈 왼쪽에서 샘플을 고르거나 명세서 사진을 올려 주세요.")

    if ss.error:
        st.error(ss.error)

    ag, status = ss.agent, ss.status
    if ag and ag.extracted:
        data = ag.extracted.model_dump()
        low = set(data.get("low_confidence_fields") or [])
        fmt = lambda v: f"{v:,}" if isinstance(v, int) else (f"{v:g}" if isinstance(v, float) else str(v))
        rows = [{"항목": FIELD_LABELS[k], "읽은 값": fmt(data[k]), "확인": "⚠️ 흐림" if k in low else ""}
                for k in FIELD_LABELS if data.get(k) not in (None, "")]
        with st.expander("🔎 명세서에서 읽은 값", expanded=bool(status and status.get("status") == "need_edit")):
            if status and status.get("status") == "need_edit":
                st.warning("틀린 값을 고친 뒤 '고친 값으로 다시 분석'을 눌러 주세요.")
                edit = {k: data[k] for k in FIELD_LABELS}
                df = pd.DataFrame([{"key": k, "항목": FIELD_LABELS[k], "값": "" if v is None else str(v)}
                                   for k, v in edit.items()])
                edited = st.data_editor(df, column_config={"key": None}, disabled=["항목"], hide_index=True)
                if st.button("✏️ 고친 값으로 다시 분석", type="primary"):
                    new = {}
                    for _, r in edited.iterrows():
                        v = r["값"].strip()
                        f = PayslipData.model_fields[r["key"]].annotation
                        if v == "":
                            new[r["key"]] = None
                        elif "int" in str(f):
                            new[r["key"]] = int(float(v.replace(",", "")))
                        elif "float" in str(f):
                            new[r["key"]] = float(v)
                        else:
                            new[r["key"]] = v
                    start_analysis(PayslipData(**new))
                    st.rerun()
            else:
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    # 질문 (Human-in-the-loop)
    if status and status.get("status") == "need_input":
        with st.container(border=True):
            st.markdown(f"### ❓ {status['question']}")
            cols = st.columns(len(status["options"]))
            for c, opt in zip(cols, status["options"]):
                if c.button(opt, width="stretch", key=f"opt_{len(ag.trace)}_{opt}"):
                    run(ag.answer, opt)
                    st.rerun()

    # 결과
    if ag and status and status.get("status") == "done" and ag.result:
        r = ag.result
        violated = [i for i in r.items if i.violated]
        st.subheader("✅ 분석 결과")
        c1, c2, c3 = st.columns(3)
        c1.metric("받지 못한 총액", f"{r.total_shortfall:,}원")
        c2.metric("위반 항목", f"{len(violated)}건")
        c3.metric("적용 최저시급", f"{r.min_hourly:,}원")
        if violated:
            st.dataframe(pd.DataFrame([{"항목": i.name, "받아야 할 금액": f"{i.expected:,}원", "받은 금액": f"{i.paid:,}원",
                                        "미지급액": f"{i.shortfall:,}원", "근거": i.law, "계산식": i.formula}
                                       for i in violated]), hide_index=True, width="stretch")
        else:
            st.success("법 기준에 맞게 지급되었어요. 🎉")
        st.caption("※ 위 금액은 AI가 아닌 계산 엔진(코드)이 법 규칙으로 계산한 값이에요.")

        st.markdown("#### 💬 Agent 설명 (" + LANG_NAMES.get(ag.language, "한국어") + ")")
        st.markdown(ag.final_text or "")

        if violated:
            st.markdown("#### 📮 다음에 할 일")
            b1, b2 = st.columns(2)
            try:
                pdf = build_complaint_pdf(ag.extracted, r, ag.centers)
                b1.download_button("📄 진정서 초안 PDF 받기", pdf, file_name="임금체불_진정서_초안.pdf",
                                   mime="application/pdf", type="primary", width="stretch")
            except Exception as e:
                ag.log("retry", "PDF 생성 실패 → 텍스트로 대체", str(e))
                b1.download_button("📄 진정서 초안 (텍스트)", ag.final_text or "", file_name="진정서_초안.txt",
                                   width="stretch")
            b2.link_button("📞 1350 고용노동부 상담 안내", "https://www.moel.go.kr", width="stretch")
            for c in ag.centers:
                st.markdown(f"- **{c['name']}** · {c['type']} · {c['how']}")
        st.warning("이 결과는 참고용이며 법률 자문이 아니에요. 최종 판단은 고용노동부 또는 공인노무사에게 확인하세요.")
        if st.button("🔄 처음부터 다시"):
            ss.agent, ss.status = None, None
            st.rerun()

with right:
    st.subheader("🤖 Agent 실행 과정")
    ag = ss.agent
    if not ag:
        st.caption("분석을 시작하면 Agent가 무엇을, 왜 하는지 여기에 단계별로 보여줘요.")
        st.markdown("📋 계획 · 🔧 도구 · 🧠 판단 · ❓ 질문 · 🛡️ 검증 · 🔁 재시도 · ✅ 결과")
    else:
        if ag.plan:
            with st.container(border=True):
                st.markdown("**📋 실행 계획**")
                for n, s in enumerate(ag.plan, 1):
                    st.markdown(f"{n}. {s}")
        for t in ag.trace:
            if t["kind"] == "plan":
                continue
            with st.container(border=True):
                st.markdown(f"{t['icon']} {t['title']}")
                if t["detail"] and t["kind"] in ("verify", "tool", "retry", "error"):
                    d = t["detail"]
                    if isinstance(d, (list, tuple)):
                        st.caption(" · ".join(map(str, d)))
                    elif isinstance(d, dict):
                        st.caption(", ".join(f"{k}={v}" for k, v in list(d.items())[:8]) + " …")
                    else:
                        st.caption(str(d)[:300])
        st.download_button("⬇️ 실행 로그(JSON) 받기 — 보고서용",
                           json.dumps(ag.trace, ensure_ascii=False, indent=2, default=str),
                           file_name="agent_trace.json", width="stretch")
