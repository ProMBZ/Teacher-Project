import os
import re
import streamlit as st
from datetime import datetime, date, time
from dateutil import parser as date_parser
from dotenv import load_dotenv
from io import BytesIO
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

# Gemini
from langchain.schema import HumanMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI

# -----------------------------------------------------------------------------
# 1. Load environment & initialize Gemini
# -----------------------------------------------------------------------------
load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")  # or rename to your env var
if not api_key:
    st.error("GOOGLE_API_KEY not found in environment variables. Please set it in your .env file.")
    st.stop()

llm = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash-exp",
    google_api_key=api_key,
    convert_system_message_to_human=True
)

# -----------------------------------------------------------------------------
# 2. Streamlit config & session
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Teacher Daily Log", page_icon="📝")

# We'll store multiple records in 'teacher_data'
# Each record: { date_str, arrival, departure, topics, is_friday, marks_M, marks_A, marks_H }
if "teacher_data" not in st.session_state:
    st.session_state["teacher_data"] = []

# For the "current day" record being built
if "ongoing_record" not in st.session_state:
    st.session_state["ongoing_record"] = {
        "date_str": None,
        "arrival": None,
        "departure": None,
        "topics": None,
        "is_friday": False,
        "muhammad_marks": None,
        "abubakar_marks": None,
        "hafsa_marks": None
    }

if "missing_fields" not in st.session_state:
    st.session_state["missing_fields"] = []

# -----------------------------------------------------------------------------
# 3. Simple Reminders: if it's after 6 PM local and no record for "today"
# -----------------------------------------------------------------------------
def check_reminder():
    now = datetime.now()
    # If after 6pm
    if now.hour >= 18:
        # Convert today's date to str: e.g., "2025-02-11"
        today_str = str(now.date())
        # Check if we have a record in teacher_data with date_str == today_str
        existing = any(rec["date_str"] == today_str for rec in st.session_state["teacher_data"])
        if not existing:
            st.warning("You haven’t logged info for today! (After 6:00 PM)")

# -----------------------------------------------------------------------------
# 4. PDF Generation
# -----------------------------------------------------------------------------
def generate_pdf():
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=LETTER)
    textobject = c.beginText()
    textobject.setTextOrigin(50, 700)
    textobject.setFont("Helvetica", 12)

    textobject.textLine("Teacher Schedule & Notes")
    textobject.textLine("------------------------------------------------")
    textobject.textLine("")
    data_list = st.session_state["teacher_data"]
    for i, rec in enumerate(data_list, start=1):
        textobject.textLine(f"Record {i}:")
        textobject.textLine(f"  Date: {rec['date_str']}")
        textobject.textLine(f"  Arrival: {rec['arrival']}")
        textobject.textLine(f"  Departure: {rec['departure']}")
        textobject.textLine(f"  Topics: {rec['topics']}")
        if rec["is_friday"]:
            textobject.textLine(f"  Friday? Yes. Marks out of 20 =>")
            textobject.textLine(f"    Muhammad: {rec['muhammad_marks']}")
            textobject.textLine(f"    Abubakar: {rec['abubakar_marks']}")
            textobject.textLine(f"    Hafsa: {rec['hafsa_marks']}")
        else:
            textobject.textLine("  Friday? No.")
        textobject.textLine("")
    c.drawText(textobject)
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer

# -----------------------------------------------------------------------------
# 5. Check for missing fields
# -----------------------------------------------------------------------------
def find_missing_fields():
    rec = st.session_state["ongoing_record"]
    needed = []
    if rec["date_str"] is None:
        needed.append("date_str")
    if rec["arrival"] is None:
        needed.append("arrival")
    if rec["departure"] is None:
        needed.append("departure")
    if rec["topics"] is None:
        needed.append("topics")
    if rec["is_friday"]:
        # Each mark is out of 20; if None we still need it
        if rec["muhammad_marks"] is None:
            needed.append("muhammad_marks")
        if rec["abubakar_marks"] is None:
            needed.append("abubakar_marks")
        if rec["hafsa_marks"] is None:
            needed.append("hafsa_marks")
    return needed

# -----------------------------------------------------------------------------
# 6. Parse user text for date, arrival, departure, topics, friday, marks
# -----------------------------------------------------------------------------
def parse_user_text(text: str):
    lower_text = text.lower()
    rec = st.session_state["ongoing_record"]

    # (a) Automatic date detection
    # Look for phrases like "for january 10th", "on 2025-01-10", etc.
    # We'll try the first dateutil parse we can find in the text.
    # A naive approach: split on "for" or "on"? Or just try dateutil parse on entire text.
    # Let's do a simple pattern approach:
    possible_dates = re.findall(r"(?:for|on)\s+([\w\s\-,]+)", text, re.IGNORECASE)
    # e.g. "on January 10th", or "for 2025-01-10"
    # Then try date_parser.parse(...) on each
    found_date = None
    for d in possible_dates:
        try:
            parsed = date_parser.parse(d.strip())
            found_date = parsed.date()
            break
        except:
            pass
    if found_date:
        rec["date_str"] = str(found_date)
    else:
        # If user didn't specify a date, default to today
        if rec["date_str"] is None:
            rec["date_str"] = str(date.today())

    # (b) If user says "friday"
    if "friday" in lower_text:
        rec["is_friday"] = True

    # (c) arrival -> "arrived at 10:40" or "came at 10:40"
    arrival_match = re.findall(r"(?:arrived|came)\s+at\s+(\d{1,2}:\d{2})", lower_text)
    if arrival_match:
        rec["arrival"] = arrival_match[-1]

    # (d) departure -> "left at 12:00" or "departed at 12:00"
    departure_match = re.findall(r"(?:left|departed)\s+at\s+(\d{1,2}:\d{2})", lower_text)
    if departure_match:
        rec["departure"] = departure_match[-1]

    # (e) topics -> "studied X" or "learned X"
    topics_match = re.search(r"(?:studied|learned)\s+(.*)", lower_text)
    if topics_match:
        rec["topics"] = topics_match.group(1).strip()

    # (f) If is_friday, parse marks for muhammad, abubakar, hafsa (out of 20)
    # e.g., "Muhammad 18", "Abubakar: 15"
    if rec["is_friday"]:
        def parse_mark(child_name: str):
            pattern = re.findall(rf"{child_name}\s*[:]*\s*(\d{{1,2}})", lower_text)
            return pattern[-1] if pattern else None

        m_mark = parse_mark("muhammad")
        if m_mark:
            rec["muhammad_marks"] = m_mark

        a_mark = parse_mark("abubakar")
        if a_mark:
            rec["abubakar_marks"] = a_mark

        h_mark = parse_mark("hafsa")
        if h_mark:
            rec["hafsa_marks"] = h_mark

# -----------------------------------------------------------------------------
# 7. Finalize record & call Gemini
# -----------------------------------------------------------------------------
def finalize_record():
    rec = st.session_state["ongoing_record"]
    st.session_state["teacher_data"].append(dict(rec))  # store a copy

    # Summarize to call Gemini
    summary = (
        f"Date: {rec['date_str']}, Arrival: {rec['arrival']}, Departure: {rec['departure']}, "
        f"Topics: {rec['topics']}, isFriday: {rec['is_friday']}, "
        f"Muhammad: {rec['muhammad_marks']}, Abubakar: {rec['abubakar_marks']}, Hafsa: {rec['hafsa_marks']}"
    )
    prompt = f"User gave teacher data:\n{summary}\nPlease reply acknowledging we've stored today's details."

    try:
        resp = llm.invoke([HumanMessage(content=prompt)])
        if isinstance(resp, AIMessage):
            gemini_reply = resp.content
        else:
            gemini_reply = str(resp)
    except Exception as e:
        gemini_reply = f"Error calling Gemini: {e}"

    st.success("All required data collected!")
    st.info(f"**Gemini**: {gemini_reply}")

    # Reset record
    st.session_state["ongoing_record"] = {
        "date_str": None,
        "arrival": None,
        "departure": None,
        "topics": None,
        "is_friday": False,
        "muhammad_marks": None,
        "abubakar_marks": None,
        "hafsa_marks": None
    }
    st.session_state["missing_fields"] = []

# -----------------------------------------------------------------------------
# 8. Main UI
# -----------------------------------------------------------------------------
def main():
    st.title("Teacher Daily Log (with Date Detection & Friday Marks)")

    # 8a. Simple reminder check if after 6pm local
    check_reminder()

    st.markdown("""
    **How to use**:
    - Type your daily info, e.g.: 
      "Teacher arrived at 10:40, left at 12:00, studied AI for January 10th"
    - If it's Friday, mention "Friday" and provide marks for Muhammad, Abubakar, Hafsa (out of 20).
      e.g. "It's Friday. Muhammad 18, Abubakar 15, Hafsa 20"
    - If you don't include a date, we default to *today*.
    """)

    user_input = st.text_area("Enter or update today's info here:")

    if st.button("Submit"):
        if not user_input.strip():
            st.warning("Please type something first.")
        else:
            parse_user_text(user_input)
            st.session_state["missing_fields"] = find_missing_fields()
            if len(st.session_state["missing_fields"]) == 0:
                finalize_record()
            else:
                st.warning("Some fields are missing. Please provide them in your next message:")
                for f in st.session_state["missing_fields"]:
                    st.write(f"- **{f}**")

    # 8b. Download PDF
    st.write("---")
    st.subheader("Download All Stored Records")
    if st.button("Get All Data (PDF)"):
        if len(st.session_state["teacher_data"]) == 0:
            st.warning("No records to download yet.")
        else:
            pdf_file = generate_pdf()
            st.download_button(
                label="Download PDF",
                data=pdf_file,
                file_name="teacher_records.pdf",
                mime="application/pdf"
            )

    # 8c. Show stored data
    st.write("---")
    st.subheader("All Stored Records So Far")
    if len(st.session_state["teacher_data"]) == 0:
        st.write("*No data yet.*")
    else:
        st.write(st.session_state["teacher_data"])

if __name__ == "__main__":
    main()
