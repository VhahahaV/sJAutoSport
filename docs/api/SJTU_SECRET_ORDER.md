# SJTU Sports 预约系统加密/解密技术总结

> 本文总结我们对**上海交通大学体育场馆预约系统**的"提交订单（ConfirmOrder）"链路的技术分析、加密/解密细节、复刻实现与通用逆向方法论，便于后续在**纯 HTTP 自动化**（无需浏览器）场景下稳定复用与举一反三。

---

## 1. 背景与目标

* **业务背景**：前端页面在提交订单时对请求体与关键头部做了加密保护，直接抓包难以复刻。
* **项目目标**：在不依赖浏览器/模拟器的前提下，使用纯 HTTP 客户端（如 `requests/httpx`）稳定提交订单：

  1. 准确生成**加密体**（AES），
  2. 正确生成**安全头**（RSA），
  3. 携带**登录态**（`JSESSIONID` 等），
  4. 避开常见"信息已过期"等业务陷阱（`sign` 时效）。

---

## 2. 交互总览（ConfirmOrder 协议概览）

### 接口

```
POST https://sports.sjtu.edu.cn/venue/personal/ConfirmOrder
```

### 头部（关键）

* `Content-Type: application/json;charset=UTF-8`
* `sid: <RSA-2048-PKCS1v1_5(Base64) of AES_key>`
* `tim: <RSA-2048-PKCS1v1_5(Base64) of timestamp_string>`
* `Cookie: JSESSIONID=...`（必须，来源于已登录会话）

> **公钥**为前端固定（极少轮换）：使用 JSEncrypt 的 RSA-2048，PKCS#1 v1.5 填充。
> PEM（示例，已实锤来自页面 `setPublicKey`）：

```
-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEArKZOdKQAL+iYzJ4Q5EQzwv/yvVPnfdNVKRgNG19HbCYM4qIzFPEOFv28SVFQh+xqAj8tAfjpMSTihFwt6BQuWfZXWYpAqf4jF4cU7ez/VHJyzsn8Cb7Lf/1KsLpuz+MbqufrA57AysnLAnRXHOwik+QnpsXZYjTcjgxQ0iLMe5iJyo06CKFxH1rmgYMwS4E89kNg1VtYrFKs1MajApfhu9hTEXnm/lP24TPdefRXbf+z84p1GLue2HRhZs3wECH1HJWZOsrdL/M+wigWldY0fHoiaKsjD9rK1NyaPtk4bIYuwPsfQu5RN4hkEPpTvdw1nKzOdo77zNa5ovCY0uNLZwIDAQAB
-----END PUBLIC KEY-----
```

### 请求体（**Base64(AES密文)**）

* 明文是标准 JSON，字段包括：
  `venTypeId, venueId, fieldType, returnUrl, scheduleDate, week, spaces[], tenSity`
* `spaces[]` 中关键字段：

  * `subSiteId`：**子场地位 ID**（固定值）
  * `scheduleTime`：时段文本 `"HH:mm-HH:mm"`
  * `sign`：**时段令牌**（**短时有效**，需"现拉现用"）
  * `venuePrice / status / venueNum / tensity / subSitename` 等

---

## 3. 客户端加密设计（最终配方）

### 3.1 对称层（体）

* **算法**：AES-128-ECB + PKCS7
* **密钥**：每次提交动态生成的 16 字符 ASCII（`[A-Z0-9]`），如 `9X4WTR3I7B83V3QQ`
* **IV**：无（`opt === undefined`，实测 ECB）
* **流程**：

  1. `payload_json = JSON.stringify(payload)`（UTF-8）
  2. `cipher = AES-128-ECB(PKCS7).encrypt(payload_json, key)`
  3. `body = Base64(cipher_bytes)` 作为 HTTP 请求体（`data`）

> 注：ECB 不带随机向量，**密文对相同明文分块是可复现的**。这也是我们能通过"前缀对比"验证算法正确性的原因。

### 3.2 非对称层（头）

* **算法**：RSA-2048 + PKCS#1 v1.5（JSEncrypt 同款）
* **sid**：`sid = Base64( RSA(pub).encrypt(key_ascii_bytes) )`
* **tim**：`tim = Base64( RSA(pub).encrypt(String(Date.now())) )`
* **长度校验**：

  * RSA 2048-bit → 密文 256 字节 → Base64 长度约 **344**（含填充 `=`）；
  * 实测 `sid/tim` Base64 前缀稳定，长度匹配。

### 3.3 业务参数要点

* `week`：此站 **周日=0 … 周六=6**。
* `subSiteId`：来自**列头** `topSite[e].fieldId`（详见 §6）。
* `sign`：短时令牌，**必须下单前刷新**（详见 §7）。

---

## 4. 服务端解密/验收（推测）

> 我们无法访问私钥，仅按常规实现+客户端行为推断。

1. **RSA 解密**：

   * 私钥解出 `AES_key`（来自 `sid`）
   * 私钥解出 `timestamp`（来自 `tim`），做**时差/重放**检查
2. **AES 解密**：

   * 以 `AES_key` + ECB/PKCS7 解 `body`
   * 反序列化为 JSON
3. **业务校验**：

   * `sign` 有效期与时段一致性
   * `subSiteId` 与 `sign` 属同一子场地位
   * 账号权限、余量、价格、限购规则
4. **入库/出单**：返回 `code=0` 及订单标识。

**常见错误**："场地信息已过期，请刷新页面"= `sign` 失效/不匹配，并非加密错误。

---

## 5. 明文数据模型（示例）

```json
{
  "venTypeId": "28d3bea9-541d-4efb-ae46-e739a5f78d72",
  "venueId": "3f009fce-10b4-4df6-94b7-9d46aef77bb9",
  "fieldType": "乒乓球",
  "returnUrl": "https://sports.sjtu.edu.cn/#/paymentResult/1",
  "scheduleDate": "2025-10-23",
  "week": "4",
  "spaces": [{
    "count": 1,
    "sign": "<短时令牌>",
    "venuePrice": "3",
    "status": 1,
    "scheduleTime": "21:00-22:00",
    "subSitename": "场地8",
    "subSiteId": "a2366636-6a6f-4199-8ba3-1d29e8c12077",
    "tensity": "1",
    "venueNum": 1
  }],
  "tenSity": "紧张"
}
```

---

## 6. `subSiteId` 的来源与定位

* 选座 JS 关键片段：

  ```js
  judgingVenueId: function(e) { return this.topSite[e].fieldId },
  // ...
  a[e][t].subSitename = this.judgingVenue(e)
  a[e][t].subSiteId   = this.judgingVenueId(e) // ← topSite[e].fieldId
  a[e][t].scheduleTime= this.period(t)
  ```
* 结论：页面的列头数组 `topSite` 就是"**子场地位清单**"，第 `e` 列对应 `topSite[e].fieldId`。
* 在页面断点处，直接打印：

  ```js
  console.table((this.topSite || []).map((s,i)=>({
    idx: i, subSiteId: s.fieldId, subSitename: s.fieldName || s.siteName || s.name
  })));
  ```
* 脚本端若需接口拉取：常见在"余票/布局"接口的 `data.topSite / subSiteList / subSiteDTOList` 中。

---

## 7. 短时令牌 `sign` 的刷新策略

* `sign` **随日期/时段变动，且短时有效**；任何缓存很快失效。
* 正确做法：**下单前立即拉余票**（或锁定接口），取目标 `subSiteId + scheduleTime` 对应的 **最新 `sign`**，马上 `ConfirmOrder`。
* 我们实践的"刷新即下单"流程：

  1. `GET /manage/fieldDetail/queryFieldSituation?...` → 解析出 `sign/price/status`
  2. 组 `payload` → 生成 `key/ts` → AES/RSA → `POST /ConfirmOrder`

---

## 8. 逆向流程复盘（可复用套路）

1. **定位提交函数**：在打包 JS 中搜索 `ConfirmOrder` 或 `agreeTerms/submit`。
2. **装三类钩子**：

   * **传输层**：Hook `fetch` / `XMLHttpRequest.send` → 记录 URL/headers/body（Base64 头部）
   * **加密层**：在**实例**上 Hook `this.Aes.encrypt` / `this.Rsa.encrypt` → 获得**明文、key、opt** 与 **RSA 明文**
   * **公钥层**：Hook `JSEncrypt.prototype.setPublicKey` → 捕获 PEM
3. **判定算法**：用页面 CryptoJS 对**同一** `key/payload` 试 **ECB vs CBC**，用 **Base64 前缀**比对，锁定 **ECB/PKCS7**。
4. **本地复刻**：用 `pycryptodome`/Node `crypto` 实现 AES/RSA，与浏览器日志对比 Base64 前缀一致即为正确。
5. **业务闭环**：加入"现拉余票→立即提交"的逻辑，避免 `sign` 失效。

> 这一套路对大量"前端 AES + 头部 RSA"的预约/下单系统通杀。

---

## 9. 本地实现（精简参考）

### 9.1 Python：加密工具

```python
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
import base64

def aes_ecb_pkcs7_encrypt_b64(key_str: str, plain: str) -> str:
    key = key_str.encode('utf-8')
    ct  = AES.new(key, AES.MODE_ECB).encrypt(pad(plain.encode('utf-8'), 16))
    return base64.b64encode(ct).decode()

def aes_ecb_pkcs7_decrypt_b64(key_str: str, b64_cipher: str) -> str:
    key = key_str.encode('utf-8')
    data = base64.b64decode(b64_cipher)
    pt = unpad(AES.new(key, AES.MODE_ECB).decrypt(data), 16)
    return pt.decode('utf-8')

def rsa_v15_encrypt_b64(pub_pem: str, data: bytes) -> str:
    pub = RSA.import_key(pub_pem)
    ct  = PKCS1_v1_5.new(pub).encrypt(data)
    return base64.b64encode(ct).decode()
```

> **解密说明**：
>
> * 我们能**AES 解密**（因为 key 就是我们生成的）；
> * 无法**RSA 解密**（服务端私钥不可得），但我们本来就知道 RSA 明文（key、timestamp），无需解。

### 9.2 Python：刷新 sign 并下单（骨架）

```python
# 1) GET 余票 → 选目标 slot → 得 sign/subSiteId/price/status
# 2) 组 payload → 生成 key/ts
# 3) body = Base64(AES-128-ECB-PKCS7(key, JSON))
# 4) sid = Base64(RSA(pub).encrypt(key))
#    tim = Base64(RSA(pub).encrypt(ts))
# 5) POST ConfirmOrder (带 Cookie)
```

> 你已有成品脚本；关键在第 1 步"**现拉现用**"。

---

## 10. 常见错误与排查

| 现象                 | 判断                   | 处理                                      |
| ------------------ | -------------------- | --------------------------------------- |
| `200` 但提示"场地信息已过期" | 加密正确、**sign 失效/不匹配** | 下单前**立即 GET 余票**；若有"锁定/校验"接口先调用         |
| `sid/tim` 长度不对     | 不是 RSA-2048 或编码问题    | 确认 PEM、确保用 **PKCS1v1.5**，Base64 长度约 344 |
| 明文能算出密文但和浏览器不一致    | AES 模式/填充不一致         | 确认 **ECB + PKCS7**；Base64 头部对比（确定性）     |
| 403/未登录            | 缺 `JSESSIONID` 或过期   | 重新登录复制 Cookie                           |
| 下单失败但无过期提示         | 业务规则                 | 限购/黑名单/超额/时段冲突，联调业务接口或看返回 `code/msg`    |
| `week` 错误          | 周索引映射不符              | 本站**周日=0..周六=6**                        |

---

## 11. 变更监测与可移植性

* **公钥轮换**：通过 `setPublicKey` 钩子可瞬时抓新 PEM，更新配置即可。
* **AES 模式变更**：重跑"**前缀对比**"实验（ECB/CBC/GCM），一眼锁定。
* **接口字段重命名**：解析时做**宽松映射**（`topSite/siteList/subSiteList/subSiteDTOList`…），或在断点处从 `this` 直接读取。
* **sign 校验增强**：若出现"锁定后下单"链路，脚本先走锁定再 Confirm。

---

## 12. 安全与合规

* 该实现仅用于**学习/个人实验**；遵守平台条款，控制请求频率，避免刷接口导致封禁或影响他人使用。
* 任何**共享/传播**脚本前，务必移除个人 Cookie、公钥之外的敏感信息。

---

## 13. 方法论速查表（TL;DR）

1. **找提交函数** → `ConfirmOrder`/`agreeTerms` 处下断点。
2. **装钩子**：`fetch/XHR`（传输）、`this.Aes.encrypt` & `this.Rsa.encrypt`（加密）、`JSEncrypt.setPublicKey`（公钥）。
3. **记三件事**：明文 JSON、`AES key`、`RSA 公钥 PEM`。
4. **判 AES**：在页面本地用 CryptoJS 试 ECB/CBC，**Base64 头前缀比对** → 选中 **ECB/PKCS7**。
5. **脚本复刻**：AES-128-ECB(PKCS7) 体，RSA-2048(v1.5) 头，带 Cookie。
6. **业务闭环**：**现拉余票**拿 `sign`，立刻下单；`subSiteId` 来自 `topSite[e].fieldId`。
7. **变更应对**：公钥轮换再抓，AES 变更再试两把，字段改名靠宽松解析或读 `this`。

---

**一句话总结**：

> 先把**加密"怎么做"**摸清（明文、key、算法、公钥），再把**业务"何时做"**跑顺（`sign` 现拉现用、`subSiteId` 对齐），就能稳定地用纯 HTTP 重现前端下单。
