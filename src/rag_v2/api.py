from http.client import HTTPException

from fastapi import FastAPI
from rag_v2.pipeline  import RETRIEVAL
from rag_v2.pipeline import query, embedder, vector_storage, doc_stores, index, model
from pydantic import BaseModel
from llama_index.core.memory import ChatMemoryBuffer
from llama_index.core.llms import ChatMessage
from uuid import UUID

from supabase import create_client, Client
from dotenv import load_dotenv
import os
load_dotenv(dotenv_path=r'C:\dev\RAG v2\.env')

# Load the secret service role key
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SERVICE_ROLE_KEY")

# This client acts as a superuser/admin
supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


memory = ChatMemoryBuffer.from_defaults(token_limit=3900)

chat_engine = index.as_chat_engine(
    chat_mode="condense_plus_context",
    memory=memory,
    llm=model,
    context_prompt=(
        "You are a chatbot, able to have normal interactions, as well as talk"
        " about different company documents"
        "Here are the relevant documents for the context:\n"
        "{context_str}"
        "\nInstruction: Use the previous chat history, or the context above, to interact and help the user."
    ),
    verbose=True,
    **RETRIEVAL
)

class QueryRequest(BaseModel):
    question:str
    chat_id: UUID
    user_id: UUID
    #history: list[ChatMessage]


app = FastAPI()


@app.get('/')
def hello():
    return {'return': 'hello world!!'}

@app.post('/query')
def queries(req:QueryRequest):
    answer = query(query=req.question)
    return {'response':answer}

@app.post('/chat')
def chatting(req:QueryRequest):
   
    result = (
    supabase_admin.table("chats")
    .select("id")
    .eq("id", str(req.chat_id))
    .eq("user_id", str(req.user_id))
    .execute()
)
    if not result.data:
            raise HTTPException(status_code=404, detail="Chat not found")
    rows = (
    supabase_admin.table("messages")
    .select("role, content")
    .eq("chat_id", str(req.chat_id))
    .order("id", desc=True)
    .limit(10)
    .execute()
).data

    history = [ChatMessage(role=r["role"], content=r["content"]) for r in reversed(rows)]
    
    
    engine = index.as_chat_engine(chat_mode="condense_plus_context", llm=model,
                              context_prompt="You answer questions about Meridian Technologies' internal documents.\n"
       "Use only the context below and the conversation so far. "
       "If the context doesn't contain the answer, say you couldn't find it in the documents.\n"
       "Questions about the conversation itself can be answered from the chat history.\n\n"
       "Context:\n{context_str}", **RETRIEVAL)
    
    answer = engine.chat(req.question, chat_history=history).response
    supabase_admin.table("messages").insert([
    {"chat_id": str(req.chat_id), "role": "user",      "content": req.question},
    {"chat_id": str(req.chat_id), "role": "assistant", "content": answer},
]).execute()
    
    return {'response':answer}