# 🌟 NOVA - AI Voice Agent

Talk to Nova with your voice, and she’ll answer back smartly ✨  
Nova uses **Gemini AI**, **Murf TTS**, **AssemblyAI STT**, **NewsAPI**, and **OpenWeather** to give a real-world conversational experience.

---

## 🚀 Features

- 🎤 Real-time speech-to-text with AssemblyAI  
- 🧠 Smart responses powered by Google Gemini  
- 🗣️ Natural voice replies using Murf AI  
- 🌦️ Weather updates with OpenWeather API  
- 📰 Latest headlines with NewsAPI  
- 🎭 Multiple personas: Pirate 🏴‍☠️, Cowboy 🤠, Robot 🤖, Friendly 🙂  

---

## 📂 Project Structure

nova-ai-voice-agent/
│── main.py
│── config.py
│── requirements.txt
│── .env
│── templates/
│ └── index.html
│── static/
│ ├── avatar_pirate.png
│ ├── avatar_cowboy.jpeg
│ ├── avatar_robot.png
│ ├── avatar_friendly.png
│ └── avatar_user.png
│── uploads/
└── outputs/

yaml
Copy code

---


## ⚙️ Setup

### 1️⃣ Clone the Repository

```bash
git clone https://github.com/your-username/nova-ai-voice-agent.git
cd nova-ai-voice-agent
2️⃣ Install Dependencies
bash
Copy code
pip install -r requirements.txt
3️⃣ Configure API Keys
Run the backend and open:
👉 http://127.0.0.1:8000

Enter your keys in the UI:

Gemini API Key

AssemblyAI API Key

Murf API Key

NewsAPI Key

OpenWeather API Key

4️⃣ Run the Server
bash
Copy code
uvicorn main:app --reload
☁️ Deployment
You can deploy Nova on Render / Railway / Vercel.

For Render:

Create a Web Service

Use Dockerfile or run:

bash
Copy code
uvicorn main:app --host 0.0.0.0 --port 8000
Add all API keys as Environment Variables

📌 Tech Stack
Backend: FastAPI, WebSockets

Frontend: HTML, JavaScript, TailwindCSS

AI: Gemini, AssemblyAI, Murf AI

APIs: OpenWeather, NewsAPI

🌟 Future Features
🌐 Multi-language support

🗣️ Customizable voice personas and accents

📊 Conversation history & analytics

📩 Email or SMS notifications for news/weather alerts

🏠 Integration with smart home devices

