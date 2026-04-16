import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
import os
import json

import tempfile
import shutil

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
FAISS_INDEX_PATH = os.path.join(DATA_DIR, "faiss.index")
METADATA_PATH = os.path.join(DATA_DIR, "metadata.json")

class VectorDB:
    def __init__(self, model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'):
        # 한국어 특화 임베딩 모델 (RAG 검색 품질 향상)
        self.encoder = SentenceTransformer(model_name)
        self.dimension = self.encoder.get_sentence_embedding_dimension()
        
        # 오프라인 데이터 폴더 생성
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)
            
        self.metadata = []
        # 캐시 파일이 있으면 오프라인 로드 (서버 재시작 최적화)
        if os.path.exists(FAISS_INDEX_PATH) and os.path.exists(METADATA_PATH):
            try:
                fd, temp_path = tempfile.mkstemp(suffix=".index")
                os.close(fd)
                shutil.copy2(FAISS_INDEX_PATH, temp_path)
                self.index = faiss.read_index(temp_path)
                os.remove(temp_path)
                
                with open(METADATA_PATH, "r", encoding="utf-8") as f:
                    self.metadata = json.load(f)
                print(f"[VectorDB] 오프라인 캐시 로드 성공 ({self.index.ntotal} vectors)")
            except Exception as e:
                print(f"[VectorDB] 캐시 로드 실패, 초기화합니다: {e}")
                self.index = faiss.IndexFlatL2(self.dimension)
                self.metadata = []
        else:
            self.index = faiss.IndexFlatL2(self.dimension)

    def add_data(self, texts, metas):
        """텍스트 데이터를 벡터화하여 FAISS에 저장"""
        if not texts:
            return
        embeddings = self.encoder.encode(texts)
        self.index.add(np.array(embeddings).astype('float32'))
        self.metadata.extend(metas)
        # 데이터를 추가할 때마다 디스크에 새로고침하여 영구 보존
        self.save_local()
        
    def save_local(self):
        """FAISS와 메타데이터를 로컬 디스크에 저장(캐싱)"""
        fd, temp_path = tempfile.mkstemp(suffix=".index")
        os.close(fd)
        
        try:
            faiss.write_index(self.index, temp_path)
            shutil.copy2(temp_path, FAISS_INDEX_PATH)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
                
        with open(METADATA_PATH, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, ensure_ascii=False, indent=2)
        
    def search(self, query, top_k=3):
        """쿼리와 가장 유사한 벡터(의미+감정)를 검색"""
        if self.index.ntotal == 0:
            return []
            
        query_vector = self.encoder.encode([query])
        distances, indices = self.index.search(np.array(query_vector).astype('float32'), top_k)
        
        results = []
        for i, idx in enumerate(indices[0]):
            if idx != -1 and idx < len(self.metadata):
                results.append({
                    "score": float(distances[0][i]),
                    "data": self.metadata[idx]
                })
        return results

vector_db = VectorDB()
