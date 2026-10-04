"""Streamlit chat interface for the airline review RAG application."""

import streamlit as st

from app.logging_config import get_logger, new_request_id, set_request_id
from app.rag import answer_question


logger = get_logger(__name__)


st.set_page_config(
    page_title="Airline Intelligence Assistant",
    page_icon="✈️",
    layout="wide",
)

st.title("✈️ Airline Intelligence Assistant")

st.caption(
    "Source-grounded answers from airline reviews "
    "and crawled web sources."
)

# Sidebar values are used to constrain retrieval for each new question.
with st.sidebar:
    st.header("Search settings")
    retrieval_mode = st.selectbox('Retrieval mode', ['vector', 'graph'],
                                  help='Graph: Neo4j selects eligible dataset reviews, then Qdrant ranks them. No silent fallback.')
    dataset_only = st.checkbox('Dataset reviews only (fair comparison)', value=False)
    route_filter = st.text_input('Exact route filter (optional)', help='Use the stored spelling, e.g. London to Doha. Restricts search to dataset reviews.')
    cabin_filter = st.selectbox('Cabin filter', ['', 'Economy Class', 'Premium Economy', 'Business Class', 'First Class'])
    if retrieval_mode == 'graph':
        st.caption('Experimental: dataset only. Specify a recognized airline, exact route, or cabin. Unknown route/cabin spellings can return no evidence.')

    selected_airline = st.selectbox(
        "Airline",
        [
            "All airlines",
            "Qatar Airways",
            "Emirates",
            "Singapore Airlines",
            "Cathay Pacific",
            "ANA",
            "Japan Airlines",
            "Turkish Airlines",
            "Lufthansa",
        ],
    )

    top_k = st.slider(
        "Number of retrieved sources",
        min_value=3,
        max_value=10,
        value=5,
    )

    st.divider()

    st.write(
        "Answers are based only on indexed "
        "project sources."
    )


if "messages" not in st.session_state:
    st.session_state.messages = []

# Streamlit reruns this file after each interaction. Reuse one identifier so
# every log entry from the same browser session can be followed together.
if "_log_session_id" not in st.session_state:
    st.session_state._log_session_id = new_request_id("ui")

set_request_id(st.session_state._log_session_id)


# Replay chat history on every Streamlit rerun.
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

        if message.get("sources"):
            with st.expander("View supporting sources"):
                for source in message["sources"]:
                    st.markdown(
                        f"""
**{source.get("source_name", "Dataset")}**  
Airline: {source.get("airline_name", "Unknown")}  
Title: {source.get("title", "Untitled")}  
URL: {source.get("source_url", "Not available")}  
Score: {source.get("score", 0):.3f}
"""
                    )
                    if source.get("review_summary"):
                        st.caption(
                            "Summary: "
                            f"{source['review_summary']}"
                        )
                    for dataset in source.get('dataset_sources', []):
                        st.caption(f"{dataset['attribution']} · {dataset['license']}")
                    st.divider()


if prompt := st.chat_input(
    "Ask about passenger experience..."
):
    logger.info(
        "event=streamlit_question_submitted airline=%s source_limit=%s",
        selected_airline,
        top_k,
    )
    # Save the visible user message before adding any internal airline filter.
    st.session_state.messages.append({
        "role": "user",
        "content": prompt,
    })

    with st.chat_message("user"):
        st.markdown(prompt)

    effective_question = prompt

    if selected_airline != "All airlines":
        effective_question = (
            f"Focus only on {selected_airline}. "
            f"Question: {prompt}"
        )

    with st.chat_message("assistant"):
        with st.spinner("Searching sources..."):
            try:
                # The RAG layer performs embedding, retrieval, and generation.
                result = answer_question(
                    question=effective_question,
                    limit=top_k,
                    retrieval_mode=retrieval_mode, route=route_filter,
                    seat_type=cabin_filter, dataset_only=dataset_only,
                )

                st.markdown(result["answer"])

                with st.expander(
                    "View supporting sources"
                ):
                    for index, source in enumerate(
                        result["sources"],
                        start=1,
                    ):
                        st.markdown(
                            f"""
### Source {index}

**Source:** {source.get("source_name", "Dataset")}  
**Airline:** {source.get("airline_name", "Unknown")}  
**Title:** {source.get("title", "Untitled")}  
**URL:** {source.get("source_url", "Not available")}  
**Similarity:** {source.get("score", 0):.3f}
"""
                        )

                        if source.get("review_summary"):
                            st.caption(
                                "Summary: "
                                f"{source['review_summary']}"
                            )

                        excerpt = (
                            source.get("text", "")[:500]
                        )

                        st.caption(excerpt)
                        for dataset in source.get('dataset_sources', []):
                            st.caption(f"{dataset['attribution']} · {dataset['license']}")
                        st.divider()

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": result["answer"],
                    "sources": result["sources"],
                })
                logger.info(
                    "event=streamlit_answer_displayed source_count=%s",
                    len(result["sources"]),
                )

            except Exception as exc:
                # Keep the chat usable and display contextual errors raised by
                # the database, vector store, embedding, or Gemini layers.
                error_message = (
                    f"Unable to answer: {exc}"
                )

                st.error(error_message)

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": error_message,
                })
                logger.error(
                    "event=streamlit_answer_failed error_type=%s",
                    type(exc).__name__,
                )
