"""Password-protected monitoring page, with opt-in read-only database coverage."""

from datetime import datetime

import streamlit as st

from app.admin import check_password, read_logs, task_activity, visible_config
from app.config import settings
from app.prompts import SYSTEM_PROMPT, TASK_DESCRIPTION


st.set_page_config(page_title="Admin · Airline Intelligence", page_icon="🛠️", layout="wide")
st.title("Admin monitor")
st.caption("Inspect application activity and the configuration loaded by this process.")

if not settings.ADMIN_PASSWORD:
    st.info("Set ADMIN_PASSWORD in your .env file, then restart Streamlit to enable this page.")
    st.stop()

if not st.session_state.get("admin_authenticated", False):
    with st.form("admin_login"):
        st.text_input("Admin password", type="password", key="admin_password_input")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        candidate = st.session_state.pop("admin_password_input", "")
        if check_password(candidate):
            st.session_state.admin_authenticated = True
            st.rerun()
        st.error("Incorrect password.")
    st.stop()

if st.sidebar.button("Sign out"):
    st.session_state.pop("admin_authenticated", None)
    st.rerun()

auto_refresh = st.sidebar.checkbox("Refresh activity every 5 seconds", value=True)
window = st.sidebar.selectbox("Recent log lines", [500, 2000, 5000], index=1)
st.sidebar.caption("Read-only monitoring. Config changes in .env require a process restart.")


@st.fragment(run_every=5 if auto_refresh else None)
def monitor():
    """Refresh only the monitoring panel while this browser session is open."""
    if not st.session_state.get("admin_authenticated", False):
        return
    st.button("Refresh now")
    rows, notice = read_logs(window)
    st.caption(f"Last refreshed: {datetime.now().astimezone():%Y-%m-%d %H:%M:%S %Z}")
    if notice:
        st.info(notice)
    metrics = st.columns(3)
    metrics[0].metric("Events in window", len(rows))
    metrics[1].metric("Errors in window", sum(r["level"] in {"ERROR", "CRITICAL"} for r in rows))
    metrics[2].metric("Request IDs in window", len({r["request_id"] for r in rows if r["request_id"] != "-"}))
    logs_tab, tasks_tab, config_tab, coverage_tab = st.tabs(["Logs", "Tasks & calls", "Model & configuration", "Data coverage"])
    with coverage_tab:
        st.caption('Load a Postgres snapshot on demand. Counts refer to stored dataset reviews, not successful Qdrant/Neo4j writes or crawled web chunks.')
        if st.button('Load data coverage'):
            try:
                from app.coverage import load_coverage
                st.session_state.coverage_snapshot = load_coverage()
                st.session_state.coverage_loaded_at = datetime.now().astimezone().isoformat(timespec='seconds')
            except (RuntimeError, ImportError) as exc:
                st.error(str(exc))
        coverage = st.session_state.get('coverage_snapshot')
        if coverage:
            st.caption('Snapshot: ' + st.session_state.coverage_loaded_at)
            st.write({'Stored reviews': coverage['reviews'], 'Airlines': len(coverage['airlines']),
                      'Without recorded provenance': coverage['unattributed'],
                      'Legacy duplicate candidates': coverage['legacy_duplicate_candidates']})
            st.caption('Sorted by fewest recent reviews, then smallest sample. Use this to prioritize collection; absence of reviews is not evidence of poor service.')
            st.dataframe(coverage['airlines'], width='stretch', hide_index=True)
            st.subheader('Sources and attribution')
            st.dataframe(coverage['sources'], width='stretch', hide_index=True)
            st.subheader('Recent dataset imports')
            st.dataframe(coverage['runs'], width='stretch', hide_index=True)
            st.caption('Matched-existing counts include reruns and cross-source matches. A Started run without a finish may have been interrupted. Older duplicate candidates are reported, not silently deleted.')
    with logs_tab:
        levels = st.multiselect("Levels", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], default=["INFO", "WARNING", "ERROR", "CRITICAL"])
        query = st.text_input("Search event, module, caller, or request ID")
        filtered = [r for r in rows if r["level"] in levels and query.casefold() in r["raw"].casefold()]
        st.dataframe([{k: v for k, v in r.items() if k != "raw"} for r in reversed(filtered)], width="stretch", hide_index=True)
        st.download_button("Download filtered logs", "\n".join(r["raw"] for r in filtered), "filtered-logs.txt", "text/plain")
    with tasks_tab:
        st.caption("Calls and operations observed in the current log window. An unmatched start may be running, interrupted, or missing its completion; this is not a live process check. Rotated logs are excluded.")
        tasks = task_activity(rows)
        status = st.selectbox("Task status", ["All", "Completed", "Failed", "Started; completion not observed"])
        st.dataframe([t for t in tasks if status == "All" or t["Status"] == status], width="stretch", hide_index=True)
        st.caption("Tasks include ingestion, crawling, retrieval, generation, and their recorded function calls. This page does not schedule or launch jobs.")
    with config_tab:
        st.subheader("Active model and service settings")
        st.json(visible_config())
        st.subheader("Assistant task")
        st.text(TASK_DESCRIPTION)
        st.subheader("System instructions")
        st.code(SYSTEM_PROMPT, language=None)
        st.caption("These shared instructions are included at the beginning of each generated RAG prompt, followed by the question and retrieved sources. They are not a separate Gemini system-message parameter.")
        st.caption("Edit GEMINI_MODEL in .env or instructions in app/prompts.py and restart the relevant app processes. These are this process's settings; separately running jobs may have different environments.")


monitor()
