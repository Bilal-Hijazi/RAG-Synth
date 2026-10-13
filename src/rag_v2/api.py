from fastapi import FastAPI
from rag_v2.pipeline  import RETRIEVAL
from rag_v2.pipeline import query, embedder, vector_storage, doc_stores
from pydantic import BaseModel

class QueryRequest(BaseModel):
    question:str


app = FastAPI()


@app.get('/')
def hello():
    return {'return': 'hello world!!'}

@app.post('/query')
def queries(req:QueryRequest):
    answer = query(query=req.question)
    return {'response':answer}