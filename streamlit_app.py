"""Streamlit chat interface for the airline review RAG application."""

import streamlit as st

from app.rag import answer_question


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
                    st.divider()


if prompt := st.chat_input(
    "Ask about passenger experience..."
):
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

                        excerpt = (
                            source.get("text", "")[:500]
                        )

                        st.caption(excerpt)
                        st.divider()

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": result["answer"],
                    "sources": result["sources"],
                })

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
