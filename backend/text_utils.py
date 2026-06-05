import requests
from bs4 import BeautifulSoup
from pdf_utils import Document, _split_sentences

def create_document_from_text(text: str, title: str = "Pasted Text") -> Document:
    paragraphs_text = text.split("\n")
    sentences = []
    paragraphs = []
    
    for para_text in paragraphs_text:
        para_sentences = _split_sentences(para_text)
        if not para_sentences:
            continue
        start = len(sentences)
        sentences.extend(para_sentences)
        paragraphs.append(list(range(start, len(sentences))))
        
    return Document(title=title, sentences=sentences, paragraphs=paragraphs)

def fetch_url_text(url: str) -> tuple[str, str]:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    title = soup.title.string if soup.title else "Web Page"
    
    # Extract text from p, h1, h2, h3, h4, h5, h6, li
    text_blocks = []
    for el in soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li']):
        t = el.get_text(separator=' ', strip=True)
        if t:
            text_blocks.append(t)
            
    return "\n".join(text_blocks), title
