import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer


MODEL_NAME = "google/flan-t5-small"

_tokenizer = None
_model = None


def generate_grounded_answer(question: str, passage: str) -> str:
    """Ask FLAN-T5 for an answer based only on one approved article passage."""
    global _tokenizer, _model

    if _tokenizer is None or _model is None:
        _tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        _model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME)
        _model.eval()

    prompt = (
        "Select the relevant answer using exact text from the approved passage. "
        "Do not add or change facts. If the passage does not answer the question, "
        "reply exactly NO_ANSWER.\n\n"
        f"Approved passage: {passage}\n\n"
        f"Question: {question}\n"
        "Answer:"
    )

    inputs = _tokenizer(
        prompt,
        return_tensors="pt",
        truncation=True,
        max_length=512,
    )

    with torch.no_grad():
        output = _model.generate(
            **inputs,
            max_new_tokens=100,
            do_sample=False,
        )

    return _tokenizer.decode(output[0], skip_special_tokens=True).strip()