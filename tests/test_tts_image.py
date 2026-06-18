import pytest
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch
from src.skills.tts.tts import TTSGenerator
from src.skills.transcription.transcription import AudioTranscriber
from src.skills.image_gen.image_gen import ImageGenerator

@pytest.mark.anyio
async def test_tts_generator_edge():
    pipeline_mock = MagicMock()
    generator = TTSGenerator(pipeline_mock)
    
    # Mock do edge_tts
    edge_tts_mock = MagicMock()
    communicate_mock = MagicMock()
    
    async def fake_save(path):
        with open(path, "w") as f:
            f.write("dummy audio")
            
    communicate_mock.save = fake_save
    edge_tts_mock.Communicate.return_value = communicate_mock
    
    with tempfile.TemporaryDirectory() as temp_dir:
        generator.output_dir = temp_dir
        with patch.dict("sys.modules", {"edge_tts": edge_tts_mock}):
            res = await generator.generate_speech("Olá Mundo", provider="edge")
            assert os.path.exists(res)
            assert res.endswith(".mp3")

@pytest.mark.anyio
async def test_audio_transcriber_groq():
    pipeline_mock = MagicMock()
    pipeline_mock.api_keys = {"groq": "test-key-groq"}
    transcriber = AudioTranscriber(pipeline_mock)
    
    res_mock = MagicMock()
    res_mock.status_code = 200
    res_mock.json.return_value = {"text": "Transcrição do áudio gerada."}
    
    with tempfile.TemporaryDirectory() as temp_dir:
        dummy_file = os.path.join(temp_dir, "test.mp3")
        with open(dummy_file, "w") as f:
            f.write("dummy audio data")
            
        with patch("requests.post") as mock_post:
            mock_post.return_value = res_mock
            
            res = await transcriber.transcribe(dummy_file, provider="groq")
            assert res == "Transcrição do áudio gerada."
            mock_post.assert_called_once()

@pytest.mark.anyio
async def test_image_generator_fal():
    pipeline_mock = MagicMock()
    generator = ImageGenerator(pipeline_mock)
    
    res_queue_mock = MagicMock()
    res_queue_mock.status_code = 200
    res_queue_mock.json.return_value = {
        "images": [{"url": "https://fal.ai/generated_image.png"}]
    }
    
    res_img_mock = MagicMock()
    res_img_mock.status_code = 200
    res_img_mock.content = b"fake-png-binary-data"
    
    with tempfile.TemporaryDirectory() as temp_dir:
        generator.output_dir = temp_dir
        with patch("requests.post") as mock_post, \
             patch("requests.get") as mock_get, \
             patch.dict("os.environ", {"FAL_KEY": "test-key-fal"}):
            
            mock_post.return_value = res_queue_mock
            mock_get.return_value = res_img_mock
            
            res = await generator.generate("Robô futurista", provider="fal")
            assert os.path.exists(res)
            assert res.endswith(".png")
            mock_post.assert_called_once()
            mock_get.assert_called_once_with("https://fal.ai/generated_image.png", timeout=30)
