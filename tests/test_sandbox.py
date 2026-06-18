import pytest
from unittest.mock import AsyncMock, patch
from src.core.execution.sandbox import is_docker_running, ensure_docker_running, execute_in_sandbox

@pytest.mark.anyio
async def test_is_docker_running_true():
    mock_proc = AsyncMock()
    mock_proc.wait = AsyncMock(return_value=0)
    mock_proc.returncode = 0
    
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        res = await is_docker_running()
        assert res is True

@pytest.mark.anyio
async def test_is_docker_running_false():
    mock_proc = AsyncMock()
    mock_proc.wait = AsyncMock(return_value=1)
    mock_proc.returncode = 1
    
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        res = await is_docker_running()
        assert res is False

@pytest.mark.anyio
async def test_ensure_docker_already_running():
    with patch("src.core.execution.sandbox.is_docker_running", return_value=True):
        res = await ensure_docker_running()
        assert res is True

@pytest.mark.anyio
async def test_ensure_docker_trigger_boot_windows():
    is_running_mock = AsyncMock(side_effect=[False, True])
    
    with patch("src.core.execution.sandbox.is_docker_running", is_running_mock), \
         patch("os.path.exists", return_value=True), \
         patch("sys.platform", "win32"), \
         patch("subprocess.Popen") as mock_popen, \
         patch("asyncio.sleep", AsyncMock()):
         
        res = await ensure_docker_running()
        assert res is True
        mock_popen.assert_called_once()

@pytest.mark.anyio
async def test_execute_in_sandbox_success():
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"hello world\n", b""))
    mock_proc.returncode = 0
    
    with patch("src.core.execution.sandbox.ensure_docker_running", return_value=True), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
         
        res = await execute_in_sandbox("print('hello world')")
        assert "hello world" in res
