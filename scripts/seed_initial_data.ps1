param(
    [string]$GatewayBase = "http://127.0.0.1:8000",
    [string]$EnvFile = ""
)
$ErrorActionPreference = "Continue"

# Read .env
if (-not $EnvFile) { $EnvFile = Join-Path (Split-Path -Parent $PSScriptRoot) ".env" }
$deepseekKey = ""
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match '^DEEPSEEK_API_KEY\s*=\s*(.+)$') { $deepseekKey = $Matches[1].Trim().Trim('"').Trim("'") }
    }
}
Write-Host "DeepSeek key loaded: $(if ($deepseekKey) {'YES'} else {'NO'})"
Write-Host "Gateway: $GatewayBase"

function Req($Method, $Path, $Body) {
    $uri = "$GatewayBase$Path"
    $headers = @{ "Content-Type" = "application/json" }
    try {
        if ($Body) {
            $json = $Body | ConvertTo-Json -Depth 10
            $resp = Invoke-RestMethod -Method $Method -Uri $uri -Headers $headers -Body $json -TimeoutSec 60
        } else {
            $resp = Invoke-RestMethod -Method $Method -Uri $uri -TimeoutSec 60
        }
        Write-Host "  $Method $Path -> OK"
        return $resp
    } catch {
        $msg = $_.Exception.Message
        $respBody = ""
        try {
            $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
            $respBody = $reader.ReadToEnd(); $reader.Close()
        } catch {}
        Write-Host "  $Method $Path -> FAIL: $msg"
        if ($respBody) { Write-Host "    Body: $($respBody.Substring(0, [Math]::Min(400,$respBody.Length)))" }
        return $null
    }
}

Write-Host "`n=== 1. Create LLM config ==="
$llm = Req POST "/api/v1/llm-configs" @{
    name = "DeepSeek-V3 默认"
    provider = "deepseek"
    model_name = "deepseek-chat"
    api_key = $deepseekKey
    api_base_url = "https://api.deepseek.com"
    default_params = @{ temperature = 0.7; max_tokens = 4096; top_p = 0.9 }
    is_default = $true
}

Write-Host "`n=== 2. Create MCP service (web search stub) ==="
$mcp = Req POST "/api/v1/mcp-services" @{
    name = "联网搜索MCP"
    description = "通过联网实时搜索，获取最新资讯、数据、事实等信息"
    mode = "sse"
    sse_url = "http://localhost:8005/mcp-sse"
    status = "disconnected"
}

Write-Host "`n=== 3. Create Skill (深度调研) ==="
$skill = Req POST "/api/v1/skills" @{
    name = "深度调研"
    description = "针对复杂话题进行多轮次、多维度、多来源的深度信息检索与综合分析，输出结构化的深度研究报告。适用于行业研究、竞品分析、技术选型、市场调研、趋势预测等复杂问题。"
    category = "research"
    version = "1.0.0"
    source = "local"
    enabled = $true
    tags = @("调研", "研究", "分析", "报告", "research")
    levels = @(
        @{ level = 0; description = "技能核心触发词与目标概述"; content = "当用户提出需要进行深度调研、行业研究、市场分析、竞品分析、技术调研、综合报告、多维度对比分析、趋势预测等复杂研究型任务时，激活本技能。`n目标：通过系统的信息检索与综合分析，输出高质量结构化调研报告。" }
        @{ level = 1; description = "技能核心流程与工作方法"; content = "核心流程：`n1. 需求分析与拆解`n2. 信息源规划与关键词设计`n3. 多轮检索与多源信息获取`n4. 交叉比对与事实核查`n5. 结构化综合与大纲构建`n6. 报告撰写与质量审查" }
        @{ level = 2; description = "详细执行策略与质量标准"; content = "质量标准：数据来源可追溯、分析逻辑清晰、报告结构完整、数据时效性优先近3个月。`n策略：标注数据获取时间；采信权威来源；限制调研范围并诚实地说明边界。" }
    )
}

Write-Host "`n=== 4. List & confirm ==="
$llms = Req GET "/api/v1/llm-configs" $null
Write-Host "  LLM total: $($llms.data.total)"
$mcps = Req GET "/api/v1/mcp-services" $null
Write-Host "  MCP total: $($mcps.data.total)"
$skills = Req GET "/api/v1/skills" $null
Write-Host "  Skill total: $($skills.data.total)"

Write-Host "`nDone."
