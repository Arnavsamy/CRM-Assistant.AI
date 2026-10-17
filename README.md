# CRM-Assistant.AI

An AI-powered outreach assistant built to help users create personalised messages, manage prospects, and improve communication efficiency. The system uses prospect information, company context, and campaign goals to generate relevant outreach content for email, LinkedIn, and other communication channels.

Demo:




<img width="400" height="250" alt="gif" src="https://github.com/user-attachments/assets/c6e536c7-3d89-433f-aff2-f66a1b274b60" />



Features:

- AI-powered outreach message generation
- Personalised email and LinkedIn message creation
- Prospect and company context analysis
- Custom tone and messaging style selection
- Multiple outreach templates
- Follow-up message generation
- Campaign and prospect management
- Message editing and refinement
- Improved response-focused communication

Tech Stack:

Python, FastAPI, Streamlit, Groq API, LLaMA, Pandas, Plotly, Natural Language Processing, REST API
How It Works:
The user enters prospect details such as their name, job title, company, industry, business requirements, and outreach objective through the application interface. The system processes this information and creates a structured prospect profile.
The collected information is then passed to the AI model along with the selected communication channel, tone, message type, and campaign objective. The model generates a personalised outreach message that is relevant to the prospect and aligned with the user’s goals.
The user can review, edit, and refine the generated message before using it. The system can also generate follow-up messages, alternative versions, and different tones such as professional, friendly, concise, or persuasive.
Finally, the application displays the generated message along with the selected prospect information, recommended follow-up content, and campaign details.


Outreach Workflow:

1. Add prospect information.
2. Enter company and business context.
3. Select the communication channel.
4. Choose the preferred tone and message type.
5. Generate a personalised outreach message.
6. Review and edit the generated content.
7. Save the message or use it in an outreach campaign.


Supported Outreach Content:

- Cold emails
- LinkedIn connection messages
- LinkedIn follow-up messages
- Sales introductions
- Partnership proposals
- Product promotion messages
- Recruitment outreach
- Customer follow-ups
- Meeting request messages
- Lead nurturing campaigns


Example Use Case:

A user provides details about a marketing manager working at a growing SaaS company. The system analyses the prospect’s role, company background, and business requirements, then generates a personalised message focused on how the product can help improve their marketing workflow.
The user can then adjust the tone, shorten the message, create a follow-up, or generate multiple variations for testing.
Project Structure:

ai_outreach_assistant/
│
├── app/
│   ├── api/
│   ├── models/
│   ├── services/
│   └── utils/
│
├── frontend/
├── data/
├── assets/
│   └── outreach-demo.gif
│
├── requirements.txt
├── .env.example
└── README.md


Future Improvements:

- CRM integration
- Email sending integration
- LinkedIn workflow integration
- Outreach campaign analytics
- Response tracking
- Automated follow-up scheduling
- Lead scoring
- A/B testing for outreach messages
- Personalised company research
- Multi-language message generation


Conclusion:

The AI Outreach Assistant simplifies the process of creating personalised and effective outreach messages. By combining prospect information with generative AI, the system helps users save time, improve message quality, and build more meaningful professional communication.

CC: Arnav Ahilasamy
