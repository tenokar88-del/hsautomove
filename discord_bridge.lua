-- ─────────────────────────────────────────────────────
--  TTS Discord 음성채널 이동 모듈
--  사용법:
--    1. HOST_TOKEN 에 발급받은 토큰 입력
--    2. BOT_URL 에 Railway 서버 URL 입력
--    3. 세션 시작 시 DiscordBridge.startSession() 호출
--    4. 이동 시    DiscordBridge.movePlayer(steamId, discordId, targetKey) 호출
--       targetKey: "main" | "private1" | "private2" | "private3" | "private4"
-- ─────────────────────────────────────────────────────

DiscordBridge = {}

local HOST_TOKEN = "여기에_발급받은_토큰_입력"
local BOT_URL    = "https://여기에_railway_url_입력"

-- 세션 데이터 (startSession 후 채워짐)
local sessionData = {
    hostSteamId   = nil,
    hostDiscordId = nil,
    channels      = {},   -- { main, private1, private2, private3, private4 }
    players       = {},   -- [ { discord_id, nickname } ]
}

-- steam_id → discord_id 매칭 테이블 (호스트가 매칭 후 채워짐)
local steamToDiscord = {}

-- ── 내부 유틸 ────────────────────────────────────────

local function postJSON(endpoint, body, callback)
    local url = BOT_URL .. endpoint
    local headers = { ["Content-Type"] = "application/json" }
    WebRequest.post(url, JSON.encode(body), function(resp)
        if resp.is_error then
            broadcastToAll("[Discord] 요청 오류: " .. resp.error, {r=1,g=0,b=0})
            return
        end
        local ok, data = pcall(JSON.decode, resp.text)
        if not ok then
            broadcastToAll("[Discord] 응답 파싱 오류", {r=1,g=0,b=0})
            return
        end
        if data.error then
            broadcastToAll("[Discord] 서버 오류: " .. data.error, {r=1,g=0.5,b=0})
            return
        end
        callback(data)
    end, headers)
end

-- ── 공개 API ─────────────────────────────────────────

--- 세션 시작 (호스트 인증 + 데이터 수신)
--- 성공 시 onSessionReady(data) 호출됨
function DiscordBridge.startSession()
    postJSON("/auth", { token = HOST_TOKEN }, function(data)
        sessionData.hostSteamId   = data.host_steam_id
        sessionData.hostDiscordId = data.host_discord_id
        sessionData.channels      = data.channels
        sessionData.players       = data.players

        broadcastToAll("[Discord] 세션 시작됨. 플레이어 매칭을 완료해 주세요.", {r=0,g=1,b=0})

        if onSessionReady then
            onSessionReady(sessionData)
        end
    end)
end

--- 스팀ID ↔ 디스코드ID 매칭 등록 (호스트가 UI에서 호출)
--- @param steamId  string
--- @param discordId string
function DiscordBridge.registerMatch(steamId, discordId)
    steamToDiscord[steamId] = discordId
end

--- 플레이어를 특정 채널로 이동
--- @param steamId   string  이동시킬 플레이어의 스팀 ID
--- @param targetKey string  "main" | "private1" | "private2" | "private3" | "private4"
function DiscordBridge.movePlayer(steamId, targetKey)
    local discordId = steamToDiscord[steamId]
    if not discordId then
        broadcastToAll("[Discord] 매칭되지 않은 플레이어: " .. steamId, {r=1,g=0.5,b=0})
        return
    end

    local targetChannelId = sessionData.channels[targetKey]
    if not targetChannelId then
        broadcastToAll("[Discord] 알 수 없는 채널 키: " .. targetKey, {r=1,g=0.5,b=0})
        return
    end

    postJSON("/move", {
        token             = HOST_TOKEN,
        steam_id          = steamId,
        discord_id        = discordId,
        target_channel_id = targetChannelId,
    }, function(data)
        -- 성공 시 별도 알림 없음 (필요하면 추가)
    end)
end

--- 현재 세션 데이터 반환 (UI 구성용)
function DiscordBridge.getSessionData()
    return sessionData
end

--- 스팀ID로 디스코드ID 조회
function DiscordBridge.getDiscordId(steamId)
    return steamToDiscord[steamId]
end
