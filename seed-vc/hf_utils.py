import os
import hashlib
from huggingface_hub import hf_hub_download

# These are immutable Hugging Face revisions already validated with this
# application.  Avoid silently following a repository's moving default branch.
_PINNED_REVISIONS = {
    "Plachta/Seed-VC": "257283f9f41585055e8f858fba4fd044e5caed6e",
    "funasr/campplus": "e4b6ede7ce16997aff4ae69fbca1f0175e2afede",
    "lj1995/VoiceConversionWebUI": "e6d0c1a17da07c33557852f9dfa2bd44cc75737d",
}
_PINNED_SHA256 = {
    ("Plachta/Seed-VC", "DiT_seed_v2_uvit_whisper_small_wavenet_bigvgan_pruned.pth"): "8ec8841b20bb46df9f7e8e570a6946a4b87b940133c7f0e778487ff33841f720",
    ("funasr/campplus", "campplus_cn_common.bin"): "3388cf5fd3493c9ac9c69851d8e7a8badcfb4f3dc631020c4961371646d5ada8",
    ("lj1995/VoiceConversionWebUI", "rmvpe.pt"): "6d62215f4306e3ca278246188607209f09af3dc77ed4232efdd069798c4ec193",
}


def _verify_pinned_file(repo_id, filename, path):
    expected = _PINNED_SHA256.get((repo_id, filename))
    if not expected:
        return path
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest().lower() != expected:
        raise RuntimeError(f"Seed-VC model integrity check failed: {repo_id}/{filename}")
    return path


def load_custom_model_from_hf(repo_id, model_filename="pytorch_model.bin", config_filename=None):
    os.makedirs("./checkpoints", exist_ok=True)
    revision = _PINNED_REVISIONS.get(repo_id)
    model_path = hf_hub_download(repo_id=repo_id, filename=model_filename, cache_dir="./checkpoints", revision=revision)
    model_path = _verify_pinned_file(repo_id, model_filename, model_path)
    if config_filename is None:
        return model_path
    config_path = hf_hub_download(repo_id=repo_id, filename=config_filename, cache_dir="./checkpoints", revision=revision)
    config_path = _verify_pinned_file(repo_id, config_filename, config_path)

    return model_path, config_path
