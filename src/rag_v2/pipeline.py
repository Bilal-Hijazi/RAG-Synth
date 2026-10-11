from llama_index.core import SimpleDirectoryReader, VectorStoreIndex
from markitdown import MarkItDown
from pathlib import Path
from llama_index.core.ingestion import IngestionPipeline
from llama_index.core.node_parser import MarkdownElementNodeParser
from llama_index.llms.groq import Groq
from llama_index.core import Settings 
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.postgres import PGVectorStore
from llama_index.storage.docstore.postgres import PostgresDocumentStore
from llama_index.core import  StorageContext
from dotenv import load_dotenv
import os

import json

load_dotenv(r'C:\dev\RAG v2\.env')
api = os.getenv('api_key')
password = os.getenv('db_pass')
print(api)
embedder = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5")
docs  = []
md = MarkItDown()
model = Groq(model='qwen/qwen3.8-27b', api_key=api, max_tokens = 512 )
Settings.llm = model
Settings.embed_model = embedder




vector_storage = PGVectorStore.from_params(
    host='db.ljphjyhjkbvaztyqrenw.supabase.co',
    database='postgres',
    user='postgres',
    port=5432,
    password=password,
    embed_dim=384,
    hybrid_search=True
)
doc_stores = PostgresDocumentStore.from_params(
      host='db.ljphjyhjkbvaztyqrenw.supabase.co',
        database='postgres',
        user='postgres',
        port=5432,
        password=password
)

context = StorageContext.from_defaults(vector_store=vector_storage, docstore=doc_stores)

paths = {'legal': r'C:\dev\RAG v2\Legal_docs' , 'financial': r'C:\dev\RAG v2\Financial', 'hr': r'C:\dev\RAG v2\HR' }
for path in paths.items():
    cons = Path(path[1]).glob('*.docx')
    for con in cons: 
        mark = md.convert(con)
        with open(con.with_suffix('.md'), 'w', encoding='utf-8') as f:
            f.write(mark.markdown)
    document = SimpleDirectoryReader(input_dir=path[1], required_exts=['.md'], filename_as_id=True).load_data()
    for doc in document:
        doc.metadata['source'] = path[0]

    docs.extend(document)


ingestion = IngestionPipeline(transformations= [

    MarkdownElementNodeParser(num_workers=1),
    embedder
    



], vector_store=vector_storage, docstore=doc_stores, docstore_strategy='upserts')


nodes = ingestion.run(documents=docs)

print(nodes)

index = VectorStoreIndex.from_vector_store(vector_store=vector_storage)


query_engine = index.as_query_engine(streaming=True,vector_store_query_mode="hybrid" ,similarity_top_k=5, sparse_top_k=5)

retriever = index.as_retriever()


with open(r'C:\dev\RAG v2\src\rag_v2\evals.json', 'r') as f:
    evals = json.load(f)

with open('results.jsonl', 'w') as h:
    for ev in evals:
        if not ev['source_docs']:          # skip negatives
            continue
        nodes = retriever.retrieve(ev['question'])
        retrieved_ids = {n.metadata['file_name'].split('_')[0] for n in nodes}
        found = set(ev['source_docs']) & retrieved_ids
        ev['correct'] = len(found) / len(ev['source_docs'])
        ev['retrieved_ids'] = sorted(retrieved_ids)
        h.write(json.dumps(ev) + "\n")

scored = [ev for ev in evals if ev['source_docs']]
strict = sum(ev['correct'] == 1 for ev in scored) / len(scored)
recall = sum(ev['correct'] for ev in scored) / len(scored)
print(f"strict hit rate: {strict:.0%} | mean source recall: {recall:.0%}")
                    



            

        
        

#streaming_response = query_engine.query(evals['question'])
#streaming_response.print_response_stream()
        
