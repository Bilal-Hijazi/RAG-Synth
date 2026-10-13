from fastapi import FastAPI
from rag_v2.pipeline  import RETRIEVAL
from rag_v2.pipeline import query, embedder, vector_storage, doc_stores, index, model
from pydantic import BaseModel
from llama_index.core.memory import ChatMemoryBuffer
from llama_index.core.llms import ChatMessage




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
    answer = chat_engine.chat(message=req.question).response
    return {'response':answer}