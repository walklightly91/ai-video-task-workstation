"""Run Demucs with a WAV writer independent of TorchCodec shared DLLs."""
import sys


def install_soundfile_writer():
    """Patch Demucs' WAV save path only; separation tensors and model stay unchanged."""
    import soundfile as sf
    from demucs import audio as demucs_audio

    def save_wav(path, source, sample_rate, encoding=None, bits_per_sample=None, **_kwargs):
        waveform = source.detach().cpu()
        if waveform.ndim == 2:
            waveform = waveform.transpose(0, 1)
        subtype = 'FLOAT' if str(encoding or '').upper() == 'PCM_F' else {
            24: 'PCM_24', 32: 'PCM_32',
        }.get(int(bits_per_sample or 16), 'PCM_16')
        sf.write(str(path), waveform.numpy(), int(sample_rate), subtype=subtype)

    demucs_audio.ta.save = save_wav


def main():
    install_soundfile_writer()
    from demucs.separate import main as demucs_main
    demucs_main()


if __name__ == '__main__':
    main()
