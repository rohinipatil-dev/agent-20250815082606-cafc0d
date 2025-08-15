import os
from typing import Optional, Tuple
import streamlit as st

# Only allowed OpenAI import
from openai import OpenAI


def init_page():
    st.set_page_config(page_title="WhatsApp Message Agent", page_icon="💬", layout="centered")
    st.title("💬 WhatsApp Message Agent")
    st.caption("Compose or refine a message with AI and send it via WhatsApp")


def get_secret(name: str, default: str = "") -> str:
    # Prefer Streamlit secrets, then environment
    try:
        return st.secrets.get(name, os.getenv(name, default))
    except Exception:
        return os.getenv(name, default)


def sidebar_config() -> Tuple[Optional[OpenAI], dict]:
    st.sidebar.header("Configuration")

    # OpenAI API Key
    openai_key = st.sidebar.text_input(
        "OpenAI API Key",
        type="password",
        value=get_secret("OPENAI_API_KEY", ""),
        help="Set as environment variable OPENAI_API_KEY or paste here."
    )
    if openai_key:
        os.environ["OPENAI_API_KEY"] = openai_key

    # Initialize OpenAI client only after key is potentially set
    client: Optional[OpenAI] = None
    if os.getenv("OPENAI_API_KEY"):
        client = OpenAI()
    else:
        st.sidebar.warning("Provide your OpenAI API key to enable AI message crafting.")

    st.sidebar.markdown("---")
    st.sidebar.subheader("Twilio WhatsApp")
    twilio_sid = st.sidebar.text_input(
        "Twilio Account SID",
        value=get_secret("TWILIO_ACCOUNT_SID", ""),
        help="Set as TWILIO_ACCOUNT_SID"
    )
    twilio_token = st.sidebar.text_input(
        "Twilio Auth Token",
        type="password",
        value=get_secret("TWILIO_AUTH_TOKEN", ""),
        help="Set as TWILIO_AUTH_TOKEN"
    )
    twilio_whatsapp_from = st.sidebar.text_input(
        "Twilio WhatsApp From (e.g., whatsapp:+14155238886)",
        value=get_secret("TWILIO_WHATSAPP_FROM", ""),
        help="Your Twilio WhatsApp-enabled sender number, prefix with 'whatsapp:'."
    )

    cfg = {
        "twilio_sid": twilio_sid.strip(),
        "twilio_token": twilio_token.strip(),
        "twilio_from": twilio_whatsapp_from.strip(),
    }
    return client, cfg


def require_twilio(cfg: dict) -> bool:
    missing = []
    if not cfg.get("twilio_sid"):
        missing.append("Account SID")
    if not cfg.get("twilio_token"):
        missing.append("Auth Token")
    if not cfg.get("twilio_from"):
        missing.append("WhatsApp From")
    if missing:
        st.error(f"Missing Twilio config: {', '.join(missing)}")
        return False
    if not cfg["twilio_from"].startswith("whatsapp:"):
        st.error("Twilio 'From' number must start with 'whatsapp:'.")
        return False
    return True


def sanitize_whatsapp_to(number: str) -> Optional[str]:
    num = number.strip()
    if not num:
        return None
    if not num.startswith("+"):
        st.error("Recipient number must be in E.164 format starting with '+', e.g., +15551234567")
        return None
    return f"whatsapp:{num}"


def generate_message_with_ai(client: OpenAI, brief: str, tone: str, extras: str, emoji: bool) -> str:
    tone_text = tone if tone.lower() != "custom" else "custom tone"
    emoji_pref = "Include a subtle, relevant emoji." if emoji else "Do not include any emoji."
    user_prompt = (
        f"Goal/Context:\n{brief.strip()}\n\n"
        f"Tone: {tone_text}\n"
        f"Additional details/constraints:\n{extras.strip()}\n\n"
        f"Instructions:\n"
        f"- Write a single concise WhatsApp message (max 500 characters).\n"
        f"- Be clear and natural, suitable for WhatsApp.\n"
        f"- If it involves a request, include a simple call-to-action.\n"
        f"- {emoji_pref}\n"
        f"- Return only the message text. No quotes, no markdown, no preface."
    )
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a helpful assistant that crafts concise, friendly WhatsApp messages."},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        max_tokens=300,
    )
    return (response.choices[0].message.content or "").strip()


def improve_message_with_ai(client: OpenAI, original: str, tone: str, shorten: bool) -> str:
    shorten_instr = "Shorten to be more concise but keep the key message." if shorten else "Keep roughly the same length."
    user_prompt = (
        f"Rewrite the following WhatsApp message to improve clarity, tone, and flow.\n"
        f"Desired tone: {tone}\n"
        f"{shorten_instr}\n"
        f"Return only the message text with no quotes or extra commentary.\n\n"
        f"Message:\n{original.strip()}"
    )
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a helpful assistant that refines short WhatsApp messages."},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.5,
        max_tokens=300,
    )
    return (response.choices[0].message.content or "").strip()


def send_whatsapp_message(cfg: dict, to_number: str, body: str) -> Optional[str]:
    try:
        from twilio.rest import Client as TwilioClient
    except ImportError:
        st.error("Twilio library not installed. Run: pip install twilio")
        return None

    try:
        client = TwilioClient(cfg["twilio_sid"], cfg["twilio_token"])
        msg = client.messages.create(
            from_=cfg["twilio_from"],
            to=to_number,
            body=body
        )
        return msg.sid
    except Exception as e:
        st.error(f"Failed to send WhatsApp message: {e}")
        return None


def init_session_state():
    if "history" not in st.session_state:
        st.session_state.history = []  # list of dicts: {to, body, sid}


def history_ui():
    st.subheader("Sent Messages")
    if not st.session_state.history:
        st.info("No messages sent yet.")
        return
    for idx, item in enumerate(reversed(st.session_state.history), start=1):
        with st.expander(f"{idx}. To: {item.get('to_display', '')} | SID: {item.get('sid', 'N/A')}"):
            st.code(item.get("body", ""), language=None)


def compose_ui(client: Optional[OpenAI], cfg: dict):
    st.subheader("Compose")

    col1, col2 = st.columns([1, 1])
    with col1:
        to_input = st.text_input("Recipient WhatsApp number (E.164, e.g., +15551234567)")
    with col2:
        send_now = st.toggle("Ready to send", value=False)

    mode = st.radio(
        "How would you like to create your message?",
        options=["I have a brief (use AI)", "I already wrote it (optional AI improve)"],
        horizontal=False
    )

    message_text = ""

    if mode == "I have a brief (use AI)":
        if client is None:
            st.warning("Enter your OpenAI API Key in the sidebar to use AI message generation.")
        brief = st.text_area("What do you want to say? (goal/context)", height=120)
        tone = st.selectbox("Tone", options=["Friendly", "Professional", "Formal", "Casual", "Apologetic", "Urgent", "Promotional", "Custom"], index=0)
        extras = st.text_area("Additional details (optional)", height=80, placeholder="Deadlines, links, constraints, etc.")
        emoji = st.checkbox("Add a subtle emoji", value=False)

        if st.button("Generate with AI", disabled=(client is None or not brief.strip())):
            with st.spinner("Thinking..."):
                try:
                    message_text = generate_message_with_ai(client, brief, tone, extras, emoji)
                    st.session_state["draft_message"] = message_text
                except Exception as e:
                    st.error(f"AI generation failed: {e}")

        message_text = st.text_area("Message (editable)", value=st.session_state.get("draft_message", ""), height=160)

    else:
        message_text = st.text_area("Your message", height=160, placeholder="Type or paste the message to send...")
        col_i1, col_i2, col_i3 = st.columns([1, 1, 2])
        with col_i1:
            improve = st.checkbox("Improve with AI", value=False)
        with col_i2:
            shorten = st.checkbox("Make shorter", value=False)
        with col_i3:
            tone = st.selectbox("Improvement tone", options=["Friendly", "Professional", "Formal", "Casual", "Apologetic", "Urgent", "Promotional"], index=0)

        if st.button("Improve Message", disabled=(client is None or not message_text.strip())):
            with st.spinner("Improving..."):
                try:
                    improved = improve_message_with_ai(client, message_text, tone, shorten)
                    st.session_state["draft_message"] = improved
                except Exception as e:
                    st.error(f"AI improvement failed: {e}")

        if "draft_message" in st.session_state and st.session_state["draft_message"]:
            message_text = st.text_area("Message (editable)", value=st.session_state["draft_message"], height=160)

    # Send controls
    st.markdown("---")
    col_s1, col_s2 = st.columns([1, 3])
    with col_s1:
        preview = st.button("Preview")
    with col_s2:
        disabled_send = not (send_now and message_text.strip() and to_input.strip())
        send = st.button("Send on WhatsApp", type="primary", disabled=disabled_send)

    if preview:
        st.info("Preview")
        st.code(message_text or "(empty)")

    if send:
        if not require_twilio(cfg):
            return
        to_whatsapp = sanitize_whatsapp_to(to_input)
        if not to_whatsapp:
            return
        with st.spinner("Sending via WhatsApp..."):
            sid = send_whatsapp_message(cfg, to_whatsapp, message_text.strip())
        if sid:
            st.success(f"Message sent! SID: {sid}")
            st.session_state.history.append({
                "to_display": to_input.strip(),
                "to": to_whatsapp,
                "body": message_text.strip(),
                "sid": sid
            })
            # Clear draft
            st.session_state["draft_message"] = ""


def main():
    init_page()
    init_session_state()
    client, cfg = sidebar_config()

    tabs = st.tabs(["Compose", "History"])
    with tabs[0]:
        compose_ui(client, cfg)
    with tabs[1]:
        history_ui()

    st.markdown("---")
    st.caption("Note: WhatsApp delivery requires a Twilio WhatsApp-enabled number and approved templates for certain use cases.")


if __name__ == "__main__":
    main()