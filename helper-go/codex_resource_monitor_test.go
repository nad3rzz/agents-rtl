package main

import (
	"math"
	"runtime"
	"testing"
	"time"
)

func TestCalculateCodexResourceMetricsUsesSampleDeltasAndPreviousTotals(t *testing.T) {
	previousTime := time.Unix(100, 0)
	currentTime := previousTime.Add(2 * time.Second)
	previousSample := codexResourcePlatformSample{
		CapturedAt:                previousTime,
		SystemCPUClockTicks:       1000,
		ProcessCPUClockTicksByKey: map[string]uint64{"10:100": 200},
		NetworkConnectionsByKey: map[string]codexResourceConnectionCounters{
			"10:55": {UploadedBytes: 1000, DownloadedBytes: 2000},
		},
	}
	currentSample := codexResourcePlatformSample{
		CapturedAt:                currentTime,
		SystemCPUClockTicks:       1800,
		ProcessCPUClockTicksByKey: map[string]uint64{"10:100": 250, "11:150": 10},
		ResidentMemoryBytes:       4096,
		NetworkConnectionsByKey: map[string]codexResourceConnectionCounters{
			"10:55": {UploadedBytes: 1100, DownloadedBytes: 2400},
			"10:56": {UploadedBytes: 50, DownloadedBytes: 100},
		},
	}

	metrics, err := calculateCodexResourceMetrics(previousSample, currentSample, 500, 700)
	if err != nil {
		t.Fatalf("calculate metrics: %v", err)
	}
	if metrics.UploadBytesPerSecond != 75 {
		t.Fatalf("upload rate = %d, expected 75", metrics.UploadBytesPerSecond)
	}
	if metrics.DownloadBytesPerSecond != 250 {
		t.Fatalf("download rate = %d, expected 250", metrics.DownloadBytesPerSecond)
	}
	if metrics.UploadedBytesTotal != 650 || metrics.DownloadedBytesTotal != 1200 {
		t.Fatalf("unexpected totals: %+v", metrics)
	}
	if metrics.ResidentMemoryBytes != 4096 {
		t.Fatalf("RAM = %d, expected 4096", metrics.ResidentMemoryBytes)
	}
	expectedCPUPercent := math.Round((60.0/800.0*float64(runtime.NumCPU())*100)*10) / 10
	if metrics.CPUPercent != expectedCPUPercent {
		t.Fatalf("CPU = %.1f, expected %.1f", metrics.CPUPercent, expectedCPUPercent)
	}
}

func TestCalculateCodexResourceMetricsRejectsBackwardsNetworkCounter(t *testing.T) {
	previousSample := codexResourcePlatformSample{
		CapturedAt:                time.Unix(100, 0),
		SystemCPUClockTicks:       1000,
		ProcessCPUClockTicksByKey: map[string]uint64{},
		NetworkConnectionsByKey: map[string]codexResourceConnectionCounters{
			"10:55": {UploadedBytes: 1000, DownloadedBytes: 2000},
		},
	}
	currentSample := codexResourcePlatformSample{
		CapturedAt:                time.Unix(101, 0),
		SystemCPUClockTicks:       1100,
		ProcessCPUClockTicksByKey: map[string]uint64{},
		NetworkConnectionsByKey: map[string]codexResourceConnectionCounters{
			"10:55": {UploadedBytes: 999, DownloadedBytes: 2000},
		},
	}

	_, err := calculateCodexResourceMetrics(previousSample, currentSample, 0, 0)
	if err == nil {
		t.Fatal("expected a backwards network counter to fail")
	}
}

func TestObserveResetRequestIDResetsTotalsOnlyAfterInitialObservation(t *testing.T) {
	monitor := codexResourceMonitor{
		uploadedBytesTotal:   500,
		downloadedBytesTotal: 700,
		previousSample:       &codexResourcePlatformSample{},
	}
	if err := monitor.observeResetRequestID("request-one"); err != nil {
		t.Fatalf("observe initial reset request: %v", err)
	}
	if monitor.uploadedBytesTotal != 500 || monitor.downloadedBytesTotal != 700 {
		t.Fatalf("initial request must not reset existing totals: %+v", monitor)
	}
	if err := monitor.observeResetRequestID("request-two"); err != nil {
		t.Fatalf("observe changed reset request: %v", err)
	}
	if monitor.uploadedBytesTotal != 0 || monitor.downloadedBytesTotal != 0 {
		t.Fatalf("changed request must reset totals: %+v", monitor)
	}
	if monitor.previousSample != nil {
		t.Fatal("changed request must clear the previous sample while sampling is disabled")
	}
}
