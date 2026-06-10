# 鎵撳寘涓庡惎鍔ㄤ紭鍖栬鏄?
## 1) exe 浣撶Н 100MB+ 鐨勬牴鍥?
- `--collect-all PyQt6` 浼氭妸 QML/Quick/3D/Multimedia/WebEngine 绛?*鏈娇鐢?*鐨勫瓙妯″潡鍏ㄩ儴鎵撳寘锛孭yQt6 鏈韩 70MB+锛屽彔鍔犲悗 100MB+銆?- `--onefile` 浼氭妸鍏ㄩ儴渚濊禆鎵撴垚鍗曟枃浠惰嚜瑙ｅ帇 exe锛屽惎鍔ㄦ椂瑕佸厛鍦?`%TEMP%` 瑙ｅ帇锛?*鍐峰惎鍔ㄦ參 1-3 绉?*銆?- 鏃?UPX 鍘嬬缉銆?
## 2) 鍙屽嚮鍚姩"澶お澶參"鐨勬牴鍥?
- onefile 鑷В鍘嬫參锛堣涓婏級銆?- Splash 纭紪鐮?`QTimer.singleShot(2000, on_ready)`锛?*鍋囪鍔犺浇 2 绉?*銆?- `paramiko` / `cryptography` 椤跺眰 import 瑙﹀彂 OpenSSL cffi 鍔ㄦ€佺粦瀹氾紝~1-3 绉掋€?- `MainWindow.__init__` 鍚庤繕 `QTimer.singleShot(300, self._delayed_init)`锛屽啀寤跺悗 300ms銆?
## 3) 鏈鏀瑰姩

### `package.bat` 閲嶆柊璁捐
- 鏀逛负 `--onedir`锛堢洰褰曟柟寮忥級鈥斺€?鍚姩鐩存帴 exec 瀛愮洰褰曢噷鐨?exe锛岀渷鍘昏嚜瑙ｅ帇銆?- 鍘绘帀 `--collect-all PyQt6`锛屾敼涓?`--collect-data=PyQt6` 鍙敹 QSS / 缈昏瘧璧勬簮銆?- exclude 40+ 涓湭鐢ㄧ殑 Qt 瀛愬寘锛圦ml / Quick / 3D / Multimedia / WebEngine / Pdf / Svg / OpenGL / Network / Sql / Test / Designer ...锛夛紝璁?PyInstaller 鐨?hook 灏戣Е鍙?C++ DLL 鏀堕泦銆?- 淇 `hidden-import=paramiko.paramiko`锛堟嫾鍐欓敊璇級銆?- 娓呯悊 `build/` `dist/` 鏃т骇鐗┿€?- **涓嶅湪 PyInstaller 闃舵鍔?UPX** 鈥斺€?缁忛獙涓?UPX 鍘嬬缉 `python3.dll` / `VCRUNTIME140.dll` 鍚?exe 鍚姩宕?"Failed to load Python DLL"銆?
### `main.py` 鍚姩娴佺▼浼樺寲
- Splash 鏄剧ず鍚庣珛鍒?`QApplication.processEvents()`锛岄伩鍏嶄富绐楀彛鏋勯€犳湡闂撮粦灞忋€?- `QTimer.singleShot(2000, on_ready)` 鏀逛负 `0`锛屼富绐楀彛 ready 鍗冲叧闂睆銆?- `MainWindow.__init__` 鎷嗘垚涓ら樁娈碉細
  - **Phase 1锛堝悓姝ャ€佹绉掔骇锛?*锛歴uper銆佽鏍囬 / 鍑犱綍銆佸崰浣?central widget 鈥斺€?绔嬪嵆杩斿洖銆?  - **Phase 2锛堢涓€涓簨浠跺惊鐜?tick锛屽紓姝ワ級**锛氶€氳繃 `QTimer.singleShot(0, self._build_ui)` 瑙﹀彂锛岄噷闈㈣窇 `_apply_style` + `init_ui` + `refresh_tree`銆?- 鏁堟灉锛歚w.show()` 鍦ㄤ富绐楀彛鏋勯€犲畬鎴愬墠灏卞凡缁忔樉绀猴紝**鐢ㄦ埛鍏堢湅鍒颁竴涓┖鐧界獥鍙ｏ紙琚?splash 閬綇鐪嬩笉鍒帮級**锛宻plash 鍏抽棴鐬棿鍐呭宸茬粡 ready銆?- 鍘绘帀绗?15 琛岀殑閲嶅 import `from PyQt6.QtGui import QFont, QColor`銆?
### `data/database.py` 璺緞纭紪鐮?- 鍘熸潵鍐欐 `D:\skills\deply\data`锛堟崲鏈哄櫒灏变涪鏁版嵁锛夈€?- 鏀逛负璺ㄥ钩鍙拌矾寰勮В鏋愶紙Windows 鐢?`%APPDATA%`锛宮acOS 鐢?`~/Library/Application Support`锛孡inux 鐢?`XDG_DATA_HOME`锛夈€?- 鍚姩鏃?*鑷姩杩佺Щ**锛氬鏋滄柊搴撴槸绌哄簱涓旇€佽矾寰勬湁鏁版嵁锛岃嚜鍔ㄥ鍒惰€佸簱鍒版柊浣嶇疆锛堝凡瀹炴祴 2 涓湇鍔″櫒 / 3 涓簲鐢?/ 53 鏉￠儴缃插巻鍙插彲姝ｅ父杩佺Щ锛屽瘑鐮佽В瀵嗘棤璇級銆?
## 4) 瀹炴祴缁撴灉

| 鎸囨爣 | 浼樺寲鍓嶏紙鎺ㄦ柇锛?| **浼樺寲鍚?* |
|------|---------------|------------|
| Splash 鍑虹幇 | ~1 绉?| **0.3-0.9 绉?* |
| 涓荤獥鍙ｅ彲瑙?| 3-5 绉?| **0.7-2.6 绉?* |
| 浣撴劅 | Splash 鍗?2 绉?+ 涓荤獥鍙ｅ張绛?2 绉?| **Splash 鍑犱箮鐬幇锛屼富绐楀彛绔嬪嵆璁╀綅** |
| exe 浣撶Н | 100MB+ 鍗曟枃浠?| **~225MB onedir**锛堟病 UPX銆佽繍琛岀ǔ瀹氾級 |
| 浣撶Н涓嬮檺 | 鈥?| **PyQt6 + paramiko 杩欐潯璺湪 ~200MB**锛圥yQt6 鑷韩 + Qt6 闈欐€侀摼鎺?FFmpeg/OpenGL/Quick锛?|

## 5) 浣撶Н鏋侀檺璇存槑

濡傛灉鎯宠"鍑犵櫨 KB"鎴栧嚑 MB 鐨勪綋绉紝**蹇呴』鎹㈡妧鏈爤**锛?
| 璺嚎 | 浜х墿澶у皬 | 鏀瑰姩閲?|
|------|----------|--------|
| PyQt6 + PyInstaller | ~200-225 MB | 鈥?|
| PyQt6 + PyInstaller + UPX锛堜笉寮€ `--strip-loadconf` / 涓嶅帇杩愯鏃?DLL锛?| ~120-150 MB | 涓紙闇€瑕佺簿缁嗚皟 DLL 鐧藉悕鍗曪級 |
| **Tauri (Rust + WebView2)** | **5-15 MB** | **澶э紙閲嶅啓 UI銆佷繚鐣欓儴缃查€昏緫锛?* |
| **Wails (Go + WebView2)** | **5-15 MB** | **澶э紙鍚屼笂锛?* |

濡傛灉璧?Tauri / Wails锛屽缓璁彟寮€涓€涓垎鏀紑鍙戯紝涓嶅姩鐜版湁 main.py銆?
## 6) 楠岃瘉鏂规硶

1. **鍐峰惎鍔?*锛歚cd D:\codexTips\deploy-tool && python main.py`锛屽簲 < 3 绉掔湅鍒颁富绐楀彛銆?2. **鎵撳寘**锛氬湪宸茶濂?PyQt6 / paramiko / cryptography / PyInstaller 鐨?Python 鐜閲岃窇 `package.bat`锛?13 绉掑乏鍙冲嚭 `dist\DeployTool\`锛岃繍琛?`dist\DeployTool\DeployTool.exe` 搴旇兘姝ｅ父璧枫€?3. **鏁版嵁杩佺Щ**锛氬垹鎺?`%APPDATA%\deploy-tool\data\deploy_tool.db`锛屽惎鍔ㄤ竴娆′細鑷姩浠?`D:\skills\deply\data\deploy_tool.db` 澶嶅埗杩囨潵锛屽懡浠よ浼氭墦 `[deploy-tool] Migrated legacy DB from ... to ...`銆?
## 7) 鏀瑰姩鏂囦欢

- `D:\codexTips\deploy-tool\main.py` 鈥斺€?5 澶勶細鍒犻噸澶?import銆?00ms鈫?ms銆侀棯灞忕珛鍗?processEvents銆?000ms鈫?ms銆乣__init__` 寮傛鍖栵紙鎷嗕负 `_build_ui` 闃舵浜岋級銆?- `D:\codexTips\deploy-tool\data\database.py` 鈥斺€?璺緞璺ㄥ钩鍙?+ 鑷姩杩佺Щ鑰?DB銆?- `D:\codexTips\deploy-tool\package.bat` 鈥斺€?绮剧畝鐨?PyInstaller onedir 鑴氭湰锛宭ean Qt excludes銆?- `D:\codexTips\deploy-tool\OPTIMIZE.md` 鈥斺€?鏈枃浠躲€

---

## 8) 二次优化（2026-06-09 续）— 从 225MB 砍到 87MB

### cleanup_qt.py —— 打包后清理脚本
发现 PyQt6-Qt6 wheel **强制捆绑整个 Qt6 SDK**（含 Quick / 3D / Pdf / Designer / Multimedia / WebEngine / Sql / Svg / OpenGL / Help / DBus / PrintSupport / Sensors / Charts ...），即使 --exclude-module 也无法剥离这些 C++ DLL，因为它们是 .dll 二进制而非 Python 模块。

cleanup_qt.py 在 PyInstaller 完成后**手动删**掉 110MB+ 未使用的 Qt6 二进制 + 13MB qml/ + 15MB plugins/，最终 **225MB → 87MB（-61%）**：

| 内容 | 大小 | 删/留 |
|------|------|-------|
| Qt6/bin/*.dll (Quick/Quick3D/Pdf/Designer/Multimedia/...) | ~140 MB | **删 84 个 .dll/.pyd，约 110 MB** |
| Qt6/qml/* (QtQml/QtQuick/QtQuick3D/QtPdf/...) | ~13 MB | **整目录删 11 个，约 13 MB** |
| Qt6/plugins/* (assetimporters/geometryloaders/multimedia/sqldrivers/...) | ~16 MB | **整目录删 15 个，约 12 MB** |
| Qt6/translations/（除 en/zh）| ~10 MB | 仅保留 en/zh |
| Qt6/qsci/（QScintilla API，用不到）| ~2 MB | 整目录删 |

### main.py 额外修复
- **Splash tick 350ms → 120ms**（5 步 ≈ 600ms）+ fade_out 200ms → 80ms —— 总 splash 约 0.7s。
- **修复 splash.close() 后主窗口自动退出的 PyQt bug**：pp.setQuitOnLastWindowClosed(False) + on_ready 加 w.raise_() / w.activateWindow()。
- **修复 hello 项目启动无响应**：原 DeployThread.run 不检查 project_path 是否存在 / 是否 Maven 项目，路径错就直接卡住。现在加 3 重校验（空 / 目录不存在 / 缺 pom.xml）并 emit inished_err 给出明确错误信息。
- **删除 6 处 QSS ox-shadow**：Qt 6.10 不支持 CSS ox-shadow，每处 hover 都打 Unknown property box-shadow 警告，污染 stderr。

### 实测数据（venv 干净，__pycache__ 已清）

| 启动方式 | 优化前 | **优化后** |
|---------|--------|-----------|
| python main.py 主窗口可见 | 1.25 s | **0.9 s** |
| dist\DeployTool\DeployTool.exe 主窗口可见 | 2.57 s | **1.4 s** |
| 启动后稳定内存 | 187 MB | **176 MB** |
| onedir 体积 | 225.6 MB | **87.4 MB (-61%)** |
| 打包耗时 | 113 s | **100 s（更小体积还更快）** |
| stderr 警告 | 6× Unknown property box-shadow | **0** |

### 体积还能不能再压？

剩下的 87MB 主要构成：
- python313.dll 5.8 MB（必需）
- cryptography/_rust.pyd 8.7 MB（paramiko 需要，Rust 编译产物，删了 SSH 登录立刻崩）
- Qt6Core/Gui/Widgets/Network.dll 等核心 Qt 库 ~20 MB（必需）
- Qt6Qml/Quick.dll 等 12 MB — **这部分其实可以再试删**，但 QML 可能在某些 widget 内部使用，留着保险
- vcodec-61/avformat-61/avutil-59/swscale-8 ~17 MB（FFmpeg 静态编解码，widget 用不到）—— **可再省 17MB**
- 大量 .qm 翻译文件 + licenses/ 元数据 ~15 MB

**理论极限 ~50-60MB onedir**（前提是再剥一层 FFmpeg + qm）。**Tauri/Wails 路线才是 5-15MB**，但用户已确认走 PyQt6 路线。