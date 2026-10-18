"""Streamlit web interface for the Request Approval Flow.

Demonstrates the core principle:
"The AI suggests; a deterministic backend decides."
- Roles: Creator (Alice, Bob) and Reviewer (Rita).
- Creators draft, improve, submit, and cancel requests.
- Reviewers receive advisory AI recommendations, inspect prompt-injection warnings,
  and execute mandatory human approval/rejection decisions.
- Live audit log and notifications table.
"""

from datetime import datetime
import os
from pathlib import Path
import sys

# Ensure project root is always on sys.path regardless of execution directory
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from dotenv import load_dotenv
load_dotenv()

import streamlit as st

from app.audit import AuditLogger
from app.notifications import NotificationManager
from app.orchestrator import Orchestrator
from app.rules import Role, Status
from app.service import RequestService, User

# Ensure data directory exists for persistent SQLite database
data_dir = Path("data")
data_dir.mkdir(parents=True, exist_ok=True)
db_path = os.getenv("DB_PATH", "data/approval_system.db")

# Page configuration
st.set_page_config(
    page_title="Prewise | Request Approval Flow",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for modern styling
st.markdown(
    """
    <style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1E293B;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        font-size: 1.05rem;
        color: #64748B;
        margin-bottom: 1.5rem;
    }
    .status-badge {
        display: inline-block;
        padding: 0.25rem 0.6rem;
        border-radius: 9999px;
        font-size: 0.8rem;
        font-weight: 600;
        text-transform: uppercase;
    }
    .status-draft { background-color: #E2E8F0; color: #475569; }
    .status-submitted { background-color: #DBEAFE; color: #1E40AF; }
    .status-approved { background-color: #DCFCE7; color: #166534; }
    .status-rejected { background-color: #FEE2E2; color: #991B1B; }
    .status-cancelled { background-color: #F1F5F9; color: #64748B; }
    .ai-disclaimer {
        background-color: #EFF6FF;
        border-left: 4px solid #3B82F6;
        padding: 0.75rem 1rem;
        margin: 0.75rem 0;
        border-radius: 4px;
        font-weight: 500;
    }
    .injection-alert {
        background-color: #FEF2F2;
        border: 2px solid #EF4444;
        padding: 1rem;
        border-radius: 6px;
        color: #991B1B;
        font-weight: 600;
        margin: 0.75rem 0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_orchestrator(db_file: str) -> Orchestrator:
    """Instantiate a shared Orchestrator connected to the persistent SQLite database."""
    service = RequestService(db_path=db_file)
    audit = AuditLogger(service._conn, service._lock)
    notifications = NotificationManager(service._conn, service._lock)
    return Orchestrator(
        service=service,
        audit_logger=audit,
        notification_manager=notifications,
    )


orchestrator = get_orchestrator(db_path)

# Synthetic users
USERS = {
    "alice": User(id="alice", role=Role.CREATOR, name="Alice (Creator)"),
    "bob": User(id="bob", role=Role.CREATOR, name="Bob (Creator)"),
    "rita": User(id="rita", role=Role.REVIEWER, name="Rita (Reviewer)"),
}

# Sidebar: User selection and system controls
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/artificial-intelligence.png", width=64)
    st.title("Prewise Approvals")
    st.markdown("**Agentic Workflow Automation**")
    st.divider()

    user_key = st.selectbox(
        "👤 Active User / Persona:",
        options=list(USERS.keys()),
        format_func=lambda k: USERS[k].name,
        index=0,
    )
    current_user = USERS[user_key]

    st.info(f"**Current Role**: `{current_user.role.value}`\n\n**User ID**: `{current_user.id}`")

    st.divider()
    st.subheader("⚙️ System Actions")
    if st.button("⏰ Run SLA Escalation Check", use_container_width=True):
        escalated = orchestrator.check_auto_escalation(threshold_hours=24.0)
        if escalated:
            st.warning(f"Escalated {len(escalated)} overdue request(s)!")
        else:
            st.success("All submitted requests are within normal SLA.")

    st.divider()
    st.caption("Environment: `LLM_PROVIDER=" + os.getenv("LLM_PROVIDER", "mock") + "`")

# Main Header
st.markdown('<div class="main-title">Request Approval Workflow</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">Core principle: <em>The AI suggests; a deterministic backend decides.</em></div>',
    unsafe_allow_html=True,
)

# Navigation tabs based on active role
if current_user.role == Role.CREATOR:
    tab_intake, tab_my_requests, tab_notifs, tab_audit = st.tabs(
        ["💬 AI Request Intake", "📋 My Requests & Drafts", "🔔 Notifications", "📜 Audit Trail"]
    )

    # --- TAB 1: CREATOR INTAKE ---
    with tab_intake:
        st.subheader("Natural Language Request Intake")
        st.write("Describe what you need in plain English. The AI Intake Agent will structure your request.")

        intake_prompt = st.text_area(
            "What would you like to request?",
            placeholder="e.g. I need approval to purchase a 34-inch curved monitor for $650 for software engineering work.",
            height=120,
        )

        col_run, col_clear = st.columns([1, 4])
        with col_run:
            run_intake = st.button("🚀 Process with AI", type="primary", use_container_width=True)

        if run_intake and intake_prompt.strip():
            with st.spinner("Analyzing request with Intake Agent..."):
                res = orchestrator.handle_intake(current_user, intake_prompt)

            if not res["ok"]:
                err = res.get("error", {})
                st.error(f"❌ Error ({err.get('code', 'UNKNOWN')}): {err.get('message', 'Failed to process intake')}")
            else:
                intake_data = res["intake"]
                if res.get("draft_created"):
                    req = res["request"]
                    st.success(f"✅ **Draft Created Successfully!** ID: `{req['id']}`")
                    st.json(req)
                else:
                    st.warning("⚠️ **Additional Information Required**")
                    st.write(f"**Extracted Title:** {intake_data.get('title')}")
                    st.write(f"**Extracted Description:** {intake_data.get('description')}")

                    if intake_data.get("missing_fields"):
                        st.markdown("**Missing Details:**")
                        for mf in intake_data["missing_fields"]:
                            st.markdown(f"- {mf}")

                    if intake_data.get("follow_up_questions"):
                        st.markdown("**Follow-up Questions:**")
                        for q in intake_data["follow_up_questions"]:
                            st.info(f"❓ {q}")

        st.divider()
        with st.expander("Or Create Request Manually (Fallback)"):
            with st.form("manual_create_form"):
                m_title = st.text_input("Title", max_chars=120)
                m_desc = st.text_area("Description", max_chars=5000)
                submit_manual = st.form_submit_button("Create Draft Manually")
                if submit_manual:
                    res = orchestrator.service.create_request(current_user, m_title, m_desc)
                    if res["ok"]:
                        st.success(f"Draft created manually! ID: {res['request']['id']}")
                        st.rerun()
                    else:
                        st.error(res["error"]["message"])

    # --- TAB 2: MY REQUESTS & DRAFTS ---
    with tab_my_requests:
        st.subheader(f"Requests by {current_user.name}")
        req_list_res = orchestrator.service.list_requests(current_user, creator_id=current_user.id)
        requests = req_list_res.get("requests", [])

        if not requests:
            st.info("No requests created yet. Use the Intake tab to start!")
        else:
            for req in requests:
                with st.expander(f"[{req['status'].upper()}] {req['title']} (ID: {req['id']})", expanded=(req['status'] == 'Draft')):
                    st.write(f"**Description:** {req['description']}")
                    st.write(f"**Created At:** {req['created_at']}")
                    st.write(f"**Status:** `{req['status']}`")

                    # Actions based on status
                    if req["status"] == Status.DRAFT.value:
                        col1, col2, col3 = st.columns(3)

                        with col1:
                            if st.button("🔍 Run Quality Check", key=f"qc_{req['id']}"):
                                with st.spinner("Evaluating with Quality-Check Agent..."):
                                    qc_res = orchestrator.check_quality(current_user, req["id"])
                                if qc_res["ok"]:
                                    st.session_state[f"qc_result_{req['id']}"] = qc_res["quality"]
                                else:
                                    st.error(qc_res["error"]["message"])

                        with col2:
                            if st.button("📤 Submit for Review", key=f"sub_{req['id']}", type="primary"):
                                sub_res = orchestrator.submit(current_user, req["id"])
                                if sub_res["ok"]:
                                    st.success("Request submitted successfully!")
                                    st.rerun()
                                else:
                                    st.error(sub_res["error"]["message"])

                        with col3:
                            if st.button("🗑️ Cancel Draft", key=f"can_{req['id']}"):
                                can_res = orchestrator.cancel(current_user, req["id"])
                                if can_res["ok"]:
                                    st.warning("Draft cancelled.")
                                    st.rerun()
                                else:
                                    st.error(can_res["error"]["message"])

                        # Display Quality Check Results if available
                        if f"qc_result_{req['id']}" in st.session_state:
                            qc = st.session_state[f"qc_result_{req['id']}"]
                            st.markdown("---")
                            st.markdown("#### 💡 AI Quality Feedback (Advisory Only)")
                            st.write(f"**Clarity Score:** {qc['clarity_score']}/5 | **Completeness Score:** {qc['completeness_score']}/5")

                            if qc.get("suggestions"):
                                st.markdown("**Suggestions:**")
                                for i, s in enumerate(qc["suggestions"]):
                                    col_s, col_acc, col_ign = st.columns([6, 1, 1])
                                    col_s.write(f"• {s}")
                                    if col_acc.button("Accept", key=f"acc_{req['id']}_{i}"):
                                        st.toast("Suggestion noted for revision!")
                                    if col_ign.button("Ignore", key=f"ign_{req['id']}_{i}"):
                                        st.toast("Suggestion ignored.")

                            if qc.get("risks"):
                                st.markdown("**Identified Risks:**")
                                for r in qc["risks"]:
                                    st.caption(f"⚠️ {r}")

                    elif req["status"] == Status.SUBMITTED.value:
                        if st.button("🚫 Cancel Submitted Request", key=f"can_sub_{req['id']}"):
                            can_res = orchestrator.cancel(current_user, req["id"], reason="Cancelled by creator before review")
                            if can_res["ok"]:
                                st.warning("Request cancelled.")
                                st.rerun()
                            else:
                                st.error(can_res["error"]["message"])

    # --- TAB 3: NOTIFICATIONS ---
    with tab_notifs:
        st.subheader("Your Notifications")
        user_notifs = orchestrator.notifications.get_notifications(recipient_id=current_user.id)
        if not user_notifs:
            st.info("No notifications.")
        else:
            for n in user_notifs:
                st.markdown(f"**[{n['timestamp'][:19]}]** {n['message']}")

    # --- TAB 4: AUDIT LOG ---
    with tab_audit:
        st.subheader("Agent Audit Trail")
        logs = orchestrator.audit.get_logs(limit=50)
        if logs:
            st.dataframe(logs, use_container_width=True)
        else:
            st.info("No audit logs yet.")

else:
    # --- REVIEWER VIEW (RITA) ---
    tab_pending, tab_history, tab_notifs, tab_audit = st.tabs(
        ["⏳ Pending Approvals", "📑 Historical Requests", "🔔 Notifications", "📜 Full Audit Log"]
    )

    with tab_pending:
        st.subheader("Submitted Requests Awaiting Review")
        st.caption("Reviewers cannot see Drafts. You make the final decision; AI is advisory.")

        # Business rule: list_requests filters out drafts for Reviewer
        submitted_res = orchestrator.service.list_requests(current_user, status=Status.SUBMITTED.value)
        sub_list = submitted_res.get("requests", [])

        if not sub_list:
            st.success("🎉 No pending requests in queue!")
        else:
            for req in sub_list:
                with st.expander(f"📌 {req['title']} | Submitted by: {req['creator_id']} (ID: {req['id']})", expanded=True):
                    st.write(f"**Request ID:** `{req['id']}`")
                    st.write(f"**Creator:** `{req['creator_id']}`")
                    st.write(f"**Description:** {req['description']}")
                    st.write(f"**Submitted At:** {req['created_at']}")

                    st.markdown("---")
                    # Review Assist Button
                    if st.button("🤖 Get AI Recommendation", key=f"ai_rec_{req['id']}"):
                        with st.spinner("Analyzing request with Review-Assist Agent..."):
                            rec_res = orchestrator.assist_review(current_user, req["id"])
                        if rec_res["ok"]:
                            st.session_state[f"rec_data_{req['id']}"] = rec_res
                        else:
                            st.error(rec_res["error"]["message"])

                    # Display AI Recommendation if fetched
                    if f"rec_data_{req['id']}" in st.session_state:
                        rec_res = st.session_state[f"rec_data_{req['id']}"]
                        rec = rec_res["recommendation"]

                        # Check for injection warning banner
                        if rec_res.get("injection_warning") or rec.get("injection_suspected"):
                            st.markdown(
                                f'<div class="injection-alert">🚨 {rec_res.get("injection_warning", "Adversarial prompt injection pattern detected!")}</div>',
                                unsafe_allow_html=True,
                            )

                        st.markdown(
                            '<div class="ai-disclaimer">ℹ️ <strong>AI suggestion - you decide</strong> (Advisory only; backend status unchanged)</div>',
                            unsafe_allow_html=True,
                        )

                        col_a, col_b, col_c = st.columns(3)
                        col_a.metric("Risk Score (1-5)", f"{rec['risk_score']} / 5")
                        col_b.metric("Priority", rec["priority"].upper())
                        col_c.metric("AI Recommendation", rec["recommendation"].upper())

                        st.write(f"**Summary:** {rec['summary']}")
                        st.write(f"**AI Reasoning:** {rec['reasoning']}")

                    st.markdown("---")
                    st.markdown("#### ⚖️ Human Decision (Mandatory Checkpoint)")

                    reason_input = st.text_input(
                        "Decision Justification / Reason (Required):",
                        key=f"reason_{req['id']}",
                        placeholder="e.g. Approved within quarterly engineering budget.",
                    )

                    col_app, col_rej = st.columns(2)
                    with col_app:
                        if st.button("✅ Approve Request", key=f"btn_app_{req['id']}", type="primary", use_container_width=True):
                            if not reason_input.strip():
                                st.error("❌ A decision reason is strictly required before approving.")
                            else:
                                dec_res = orchestrator.human_decision(
                                    actor=current_user,
                                    request_id=req["id"],
                                    decision="approve",
                                    reason=reason_input,
                                )
                                if dec_res["ok"]:
                                    st.success(f"Request {req['id']} Approved!")
                                    st.rerun()
                                else:
                                    st.error(dec_res["error"]["message"])

                    with col_rej:
                        if st.button("❌ Reject Request", key=f"btn_rej_{req['id']}", use_container_width=True):
                            if not reason_input.strip():
                                st.error("❌ A decision reason is strictly required before rejecting.")
                            else:
                                dec_res = orchestrator.human_decision(
                                    actor=current_user,
                                    request_id=req["id"],
                                    decision="reject",
                                    reason=reason_input,
                                )
                                if dec_res["ok"]:
                                    st.warning(f"Request {req['id']} Rejected.")
                                    st.rerun()
                                else:
                                    st.error(dec_res["error"]["message"])

    with tab_history:
        st.subheader("Historical Decisions")
        hist_res = orchestrator.service.list_requests(current_user)
        non_drafts = [r for r in hist_res.get("requests", []) if r["status"] != Status.SUBMITTED.value]
        if non_drafts:
            st.dataframe(non_drafts, use_container_width=True)
        else:
            st.info("No finalized requests yet.")

    with tab_notifs:
        st.subheader("Reviewer Notifications")
        rev_notifs = orchestrator.notifications.get_notifications(recipient_id="all_reviewers")
        for n in rev_notifs:
            st.markdown(f"**[{n['timestamp'][:19]}]** {n['message']}")

    with tab_audit:
        st.subheader("Complete Agent Audit Log")
        all_logs = orchestrator.audit.get_logs(limit=100)
        st.dataframe(all_logs, use_container_width=True)
