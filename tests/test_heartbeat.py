import asyncio
import os
import pytest
import tempfile
import time
from unittest.mock import MagicMock, patch
from src.channels.telegram.heartbeat import start_heartbeat_loop

@pytest.mark.anyio
async def test_heartbeat_writes_file_and_cleans_scratch():
    with tempfile.TemporaryDirectory() as temp_dir:
        # Define caminhos
        hb_file = os.path.join(temp_dir, "bot_heartbeat.txt")
        scratch_dir = os.path.join(temp_dir, "scratch")
        os.makedirs(scratch_dir, exist_ok=True)
        
        # Cria arquivo novo (deve ser mantido)
        new_file = os.path.join(scratch_dir, "new.txt")
        with open(new_file, "w") as f:
            f.write("new content")
            
        # Cria arquivo antigo (deve ser deletado)
        old_file = os.path.join(scratch_dir, "old.txt")
        with open(old_file, "w") as f:
            f.write("old content")
        
        # Seta data de modificação antiga (8 dias atrás)
        past_time = time.time() - 8 * 86400
        os.utime(old_file, (past_time, past_time))
        
        # Aplica mocks de ambiente e constante
        with patch("src.channels.telegram.heartbeat.HEARTBEAT_FILE", hb_file), \
             patch.dict(os.environ, {"SCRATCH_DIR": scratch_dir, "GDRIVE_PATH": temp_dir}):
            
            stop_event = asyncio.Event()
            stop_event.set()
            
            pipeline_mock = MagicMock()
            
            await start_heartbeat_loop(pipeline_mock, stop_event)
            
            # 1. Verifica se o heartbeat foi escrito com sucesso
            assert os.path.exists(hb_file)
            
            # 2. Verifica se o arquivo antigo foi limpo de forma preventiva
            assert not os.path.exists(old_file)
            
            # 3. Verifica se o arquivo novo foi preservado
            assert os.path.exists(new_file)
