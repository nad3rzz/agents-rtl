//go:build linux

package main

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestParseLinuxProcessStatReadsCPUAndStartTime(t *testing.T) {
	fieldsAfterCommand := make([]string, 20)
	for index := range fieldsAfterCommand {
		fieldsAfterCommand[index] = "0"
	}
	fieldsAfterCommand[0] = "S"
	fieldsAfterCommand[11] = "20"
	fieldsAfterCommand[12] = "5"
	fieldsAfterCommand[19] = "999"
	statText := fmt.Sprintf("123 (codex worker) %s", strings.Join(fieldsAfterCommand, " "))

	processStat, err := parseLinuxProcessStat(123, statText)
	if err != nil {
		t.Fatalf("parse process stat: %v", err)
	}
	if processStat.CPUClockTicks != 25 {
		t.Fatalf("CPU ticks = %d, expected 25", processStat.CPUClockTicks)
	}
	if processStat.StartTime != 999 {
		t.Fatalf("start time = %d, expected 999", processStat.StartTime)
	}
}

func TestCodexResourcePlatformSampleIntegration(t *testing.T) {
	extensionHostProcessIDText := os.Getenv("AGENTS_RTL_TEST_EXTENSION_HOST_PID")
	if extensionHostProcessIDText == "" {
		t.Skip("AGENTS_RTL_TEST_EXTENSION_HOST_PID is not set")
	}
	extensionHostProcessID, err := strconv.Atoi(extensionHostProcessIDText)
	if err != nil {
		t.Fatalf("invalid Extension Host PID: %v", err)
	}

	previousSample, err := readCodexResourcePlatformSample(extensionHostProcessID)
	if err != nil {
		t.Fatalf("read first resource sample: %v", err)
	}
	time.Sleep(time.Second)
	currentSample, err := readCodexResourcePlatformSample(extensionHostProcessID)
	if err != nil {
		t.Fatalf("read second resource sample: %v", err)
	}
	metrics, err := calculateCodexResourceMetrics(previousSample, currentSample, 0, 0)
	if err != nil {
		t.Fatalf("calculate integration metrics: %v", err)
	}
	t.Logf("Codex resource metrics: %+v", metrics)
}

func TestParseLinuxSSNetworkConnectionCountersScopesByProcessID(t *testing.T) {
	commandOutput := []byte(strings.Join([]string{
		`ESTAB 0 0 127.0.0.1:1000 1.1.1.1:443 users:(("codex",pid=12,fd=7)) uid:1000 ino:55 sk:1`,
		` cubic bytes_acked:150 bytes_received:275`,
		`ESTAB 0 0 127.0.0.1:1001 1.1.1.1:443 users:(("codex",pid=99,fd=8)) uid:1000 ino:56 sk:2`,
		` cubic bytes_acked:900 bytes_received:1000`,
	}, "\n"))

	connections, err := parseLinuxSSNetworkConnectionCounters(commandOutput, map[int]bool{12: true})
	if err != nil {
		t.Fatalf("parse ss counters: %v", err)
	}
	if len(connections) != 1 {
		t.Fatalf("connection count = %d, expected 1", len(connections))
	}
	counters, exists := connections["12:55"]
	if !exists {
		t.Fatalf("expected connection key 12:55, got %v", connections)
	}
	if counters.UploadedBytes != 150 || counters.DownloadedBytes != 275 {
		t.Fatalf("unexpected counters: %+v", counters)
	}
}
