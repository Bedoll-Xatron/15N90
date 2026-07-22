Set WshShell = CreateObject("WScript.Shell")
' pm2를 통해 검은색 도스창(콘솔) 없이 백그라운드에서 봇을 실행합니다.
WshShell.Run "cmd /c cd /d ""D:\Project2026\15N90\one_candle_bot"" && pm2 restart one_candle_mock || pm2 start mock_trader.py --interpreter python --name ""one_candle_mock""", 0, False
