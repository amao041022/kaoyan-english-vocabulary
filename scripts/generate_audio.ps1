# 根据主程序生成的清单制作离线美音 WAV；仅使用 Windows 自带语音。
param([string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$manifestPath = Join-Path $ProjectRoot 'output/audio_manifest.json'
$audioFolder = Join-Path $ProjectRoot 'output/audio'
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
New-Item -ItemType Directory -Path $audioFolder -Force | Out-Null
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $voice = $synth.GetInstalledVoices() | Where-Object {
        $_.Enabled -and $_.VoiceInfo.Culture.Name -eq 'en-US' -and $_.VoiceInfo.Name -eq 'Microsoft Zira Desktop'
    } | Select-Object -First 1
    if (-not $voice) {
        throw '未找到 Microsoft Zira Desktop 美音语音包。请安装 Windows 英语（美国）语音后重试；不会用其他口音替代。'
    }
    $synth.SelectVoice($voice.VoiceInfo.Name)
    $synth.Rate = 0
    $synth.Volume = 100
    $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
        22050,
        [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
        [System.Speech.AudioFormat.AudioChannel]::Mono
    )
    $created = 0
    $skipped = 0
    foreach ($item in $manifest) {
        if ($item.key -notmatch '^[a-f0-9]{24}$') { throw '音频文件名校验失败' }
        $target = Join-Path $audioFolder ($item.key + '.wav')
        if ((Test-Path -LiteralPath $target) -and (Get-Item -LiteralPath $target).Length -gt 44) {
            $skipped++
            continue
        }
        # 先写入临时文件，只有完整合成后才替换目标，防止中断留下半个音频。
        $temporary = $target + '.partial'
        $synth.SetOutputToWaveFile($temporary, $format)
        $synth.Speak([string]$item.text)
        $synth.SetOutputToNull()
        Move-Item -LiteralPath $temporary -Destination $target -Force
        $created++
        if ($created % 50 -eq 0) { Write-Output ("Generated " + $created + " audio files") }
    }
    $metadata = @{
        voice = $voice.VoiceInfo.Name
        language = 'en-US'
        sample_rate = 22050
        channels = 1
        bits_per_sample = 16
        expected_files = $manifest.Count
        generated_at = (Get-Date).ToString('s')
    }
    $metadata | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $audioFolder 'voice.json') -Encoding UTF8
    Write-Output ("US audio completed: created=" + $created + ", reused=" + $skipped)
} finally {
    $synth.Dispose()
}
