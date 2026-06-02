"""多媒体检索引擎 — jieba TF-IDF/BM25 文本检索 + CLIP 图片检索。"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import jieba


# ─── 文本预处理 ────────────────────────────────────────────────

CN_STOPWORDS = {
    "的", "了", "和", "是", "在", "用", "有", "不", "这", "也", "就", "都",
    "一个", "一些", "可以", "自己", "什么", "怎么", "如何", "为什么",
    "因为", "所以", "但是", "还是", "没有", "已经", "这个", "那个",
    "我们", "他们", "你们", "它们", "她", "他", "它", "我", "你",
}


def normalize(text: str) -> str:
    """转小写、统一空白。"""
    return re.sub(r"\s+", " ", text.strip().lower())


def tokenize(text: str) -> List[str]:
    """jieba 中文分词 + 英文词拆分。"""
    if not text:
        return []
    text = normalize(text)
    tokens: List[str] = []

    # 中文词
    cn_words = jieba.lcut(text)
    for w in cn_words:
        w = w.strip()
        if len(w) > 1 and w not in CN_STOPWORDS:
            tokens.append(w)

    # 英文词（保留原始 + 变体）
    en_tokens = re.findall(r"[a-z0-9][a-z0-9+#._-]*", text)
    for t in en_tokens:
        if len(t) > 1:
            tokens.append(t)
            # 拆分连字符
            for part in re.split(r"[-_./]+", t):
                if len(part) > 1 and part != t:
                    tokens.append(part)

    return tokens


# ─── IR 引擎 ───────────────────────────────────────────────────

class MultimediaIR:
    """混合检索引擎：TF-IDF 余弦 + BM25 图像 + CLIP 图像。

    使用方式：
        ir = MultimediaIR()
        ir.build_index(videos)          # 离线构建
        results = ir.search("搞笑视频")   # 在线查询
    """

    def __init__(self):
        self.videos: List[Dict] = []
        # 文本索引
        self.postings: Dict[str, Dict[int, float]] = defaultdict(dict)  # term → {doc_id: tf}
        self.idf: Dict[str, float] = {}
        self.doc_norms: Dict[int, float] = {}
        self.bm25_idf: Dict[str, float] = {}
        self.doc_lengths: Dict[int, int] = {}
        self.avg_doc_length: float = 0.0
        # 图片索引
        self.clip_model = None
        self.clip_processor = None
        self.image_embeddings: Optional[Any] = None  # torch tensor
        self._clip_available = False
        # 字段权重
        self.field_weights = {"title": 4.0, "description": 2.0, "category": 3.0, "owner_name": 1.0}

    # ── 索引构建 ─────────────────────────────────────────────

    def build_index(self, videos: List[Dict]) -> None:
        """构建 TF-IDF + BM25 倒排索引。"""
        self.videos = videos
        N = len(videos)

        # 第一遍：文档词频
        doc_tfs: List[Dict[str, float]] = []
        for i, v in enumerate(videos):
            tf_map: Dict[str, float] = defaultdict(float)
            for field, weight in self.field_weights.items():
                for token in tokenize(str(v.get(field, ""))):
                    tf_map[token] += weight
            doc_tfs.append(tf_map)
            self.doc_lengths[i] = int(sum(tf_map.values()))

        self.avg_doc_length = sum(self.doc_lengths.values()) / max(N, 1)

        # 倒排索引
        for i, tf_map in enumerate(doc_tfs):
            for token, tf_val in tf_map.items():
                self.postings[token][i] = tf_val

        # IDF
        for token, docs in self.postings.items():
            df = len(docs)
            self.idf[token] = math.log((N - df + 0.5) / (df + 0.5) + 1.0)
            self.bm25_idf[token] = math.log(1 + (N - df + 0.5) / (df + 0.5))

        # 文档 L2 范数
        for i, tf_map in enumerate(doc_tfs):
            norm = math.sqrt(sum((tf_val * self.idf.get(tok, 0)) ** 2 for tok, tf_val in tf_map.items()))
            self.doc_norms[i] = max(norm, 1e-9)

    # ── 搜索 ─────────────────────────────────────────────────

    def search(
        self,
        query: str = "",
        top_k: int = 10,
        tfidf_weight: float = 0.35,
        bm25_weight: float = 0.35,
        image_weight: float = 0.30,
        image_query: Optional[str] = None,
        min_score: float = 0.0,
    ) -> List[Dict]:
        """混合搜索：TF-IDF + BM25 + CLIP 图片。

        Args:
            query: 文本查询（中文/英文）
            top_k: 返回结果数
            tfidf_weight/bm25_weight/image_weight: 三路融合权重
            image_query: 图片查询（支持文字描述图片内容，如"红色背景的游戏封面"）
            min_score: 最低相关性分数阈值，低于此值的结果直接舍弃。
                       纯文本检索建议 0.0（无匹配 token 时分数自然为 0），
                       混合/图片模式建议 0.0~0.5 根据 CLIP 噪声水平调节。
        """
        query_tokens = tokenize(query) if query else []
        final_scores: Dict[int, float] = defaultdict(float)

        # 1) TF-IDF 余弦
        if query_tokens and tfidf_weight > 0:
            query_tf: Dict[str, float] = defaultdict(float)
            for t in query_tokens:
                query_tf[t] += 1.0

            query_vec = {}
            for t, tf_val in query_tf.items():
                if t in self.idf:
                    query_vec[t] = (1 + math.log(tf_val)) * self.idf[t]
            q_norm = math.sqrt(sum(v ** 2 for v in query_vec.values())) or 1e-9

            for doc_id in range(len(self.videos)):
                dot = 0.0
                for t, qv in query_vec.items():
                    if t in self.postings and doc_id in self.postings[t]:
                        doc_tf = self.postings[t][doc_id]
                        dot += qv * ((1 + math.log(doc_tf)) * self.idf[t])
                score = dot / (q_norm * self.doc_norms.get(doc_id, 1e-9))
                final_scores[doc_id] += tfidf_weight * score

        # 2) BM25
        if query_tokens and bm25_weight > 0:
            k1, b_val = 1.5, 0.75
            for doc_id in range(len(self.videos)):
                dl = self.doc_lengths.get(doc_id, 1)
                score = 0.0
                for t in set(query_tokens):
                    if t in self.bm25_idf and t in self.postings and doc_id in self.postings[t]:
                        tf_d = self.postings[t][doc_id]
                        score += self.bm25_idf[t] * (tf_d * (k1 + 1)) / (tf_d + k1 * (1 - b_val + b_val * dl / self.avg_doc_length))
                final_scores[doc_id] += bm25_weight * score

        # 3) CLIP 图片检索（延迟加载）
        if image_weight > 0 and (query or image_query):
            image_scores = self._clip_search(query or image_query or "")
            if image_scores:
                for doc_id, score in image_scores.items():
                    final_scores[doc_id] += image_weight * score

        # 排序 + 阈值过滤
        ranked = [(doc_id, score) for doc_id, score in final_scores.items() if score > min_score]
        ranked.sort(key=lambda x: -x[1])
        ranked = ranked[:top_k]

        results = []
        for doc_id, score in ranked:
            v = self.videos[doc_id].copy()
            v["score"] = round(score, 4)
            v["doc_id"] = doc_id
            results.append(v)

        return results

    # ── CLIP 图片检索 ─────────────────────────────────────────

    def _load_clip(self):
        """延迟加载 CLIP 模型（仅首次使用时下载）。"""
        if self._clip_available:
            return True
        try:
            import torch
            from transformers import CLIPProcessor, CLIPModel
            model_name = "openai/clip-vit-base-patch32"
            self.clip_model = CLIPModel.from_pretrained(model_name)
            self.clip_processor = CLIPProcessor.from_pretrained(model_name)
            self._clip_available = True
            return True
        except Exception as e:
            print(f"⚠ CLIP 加载失败（将仅使用文本检索）: {e}")
            return False

    def _get_image_embeddings(self) -> Optional[Any]:
        """计算所有视频封面的 CLIP embedding（缓存）。"""
        if self.image_embeddings is not None:
            return self.image_embeddings
        if not self._load_clip():
            return None

        import torch
        from PIL import Image

        images = []
        valid_indices = []
        for i, v in enumerate(self.videos):
            cover_path = v.get("cover_local", "")
            if cover_path and Path(cover_path).exists():
                try:
                    img = Image.open(cover_path).convert("RGB")
                    images.append(img)
                    valid_indices.append(i)
                except Exception:
                    images.append(Image.new("RGB", (224, 224), (128, 128, 128)))
                    valid_indices.append(i)
            else:
                # 无图片的用灰图占位
                images.append(Image.new("RGB", (224, 224), (128, 128, 128)))
                valid_indices.append(i)

        inputs = self.clip_processor(images=images, return_tensors="pt", padding=True)
        with torch.no_grad():
            embeddings = self.clip_model.get_image_features(**inputs)
            embeddings = embeddings / embeddings.norm(dim=-1, keepdim=True)

        self.image_embeddings = embeddings
        return embeddings

    def _clip_search(self, text_query: str) -> Dict[int, float]:
        """用文字描述搜图片（CLIP zero-shot）。"""
        embeddings = self._get_image_embeddings()
        if embeddings is None:
            return {}

        import torch

        # 中英文都试试
        queries = [text_query]
        if any('\u4e00' <= c <= '\u9fff' for c in text_query):
            # 中文查询，也试试英文翻译？CLIP 对中文支持较差
            # 简单策略：直接用原文本
            pass

        text_inputs = self.clip_processor(text=queries, return_tensors="pt", padding=True)
        with torch.no_grad():
            text_emb = self.clip_model.get_text_features(**text_inputs)
            text_emb = text_emb / text_emb.norm(dim=-1, keepdim=True)

        similarities = (embeddings @ text_emb.T).squeeze(-1)
        scores: Dict[int, float] = {}
        for i, sim in enumerate(similarities.tolist()):
            scores[i] = float(sim)
        return scores


# ─── CLI ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="多媒体检索")
    parser.add_argument("--data", default="data/bilibili_videos.json", help="数据文件")
    parser.add_argument("--build", action="store_true", help="构建索引")
    parser.add_argument("query", nargs="?", default="", help="搜索查询")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--image-only", action="store_true", help="仅图片检索")
    args = parser.parse_args()

    data_path = Path(args.data)
    if not data_path.exists():
        data_path = Path(__file__).parent / args.data

    videos = json.loads(data_path.read_text(encoding="utf-8"))

    ir = MultimediaIR()
    ir.build_index(videos)

    if args.build or not args.query:
        print(f"✅ 索引构建完成: {len(videos)} 个视频")
        if args.build:
            exit(0)

    if args.query:
        iw = 0.9 if args.image_only else 0.3
        tw = 0.05 if args.image_only else 0.35
        bw = 0.05 if args.image_only else 0.35

        print(f"\n🔍 搜索: \"{args.query}\"")
        results = ir.search(args.query, top_k=args.top_k, tfidf_weight=tw, bm25_weight=bw, image_weight=iw)

        for i, r in enumerate(results):
            print(f"  {i+1}. [{r['category']}] {r['title'][:60]}  (score={r['score']:.4f})")
            if r.get("description"):
                print(f"     {r['description'][:80]}")
