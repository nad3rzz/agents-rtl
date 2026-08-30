package main

import (
	"fmt"
	"math"
	"runtime"
	"time"
)

type codexResourceConnectionCounters struct {
	UploadedBytes   uint64
	DownloadedBytes uint64
}

type codexResourcePlatformSample struct {
	CapturedAt                time.Time
	SystemCPUClockTicks       uint64
	ProcessCPUClockTicksByKey map[string]uint64
	ResidentMemoryBytes       uint64
	NetworkConnectionsByKey   map[string]codexResourceConnectionCounters
}

type codexResourceMetrics struct {
	Supported                  bool    `json:"supported"`
	SamplingEnabled            bool    `json:"samplingEnabled"`
	Initializing               bool    `json:"initializing"`
	UploadBytesPerSecond       uint64  `json:"uploadBytesPerSecond"`
	DownloadBytesPerSecond     uint64  `json:"downloadBytesPerSecond"`
	UploadedBytesTotal         uint64  `json:"uploadedBytesTotal"`
	DownloadedBytesTotal       uint64  `json:"downloadedBytesTotal"`
	ResidentMemoryBytes        uint64  `json:"residentMemoryBytes"`
	CPUPercent                 float64 `json:"cpuPercent"`
	CapturedAtUnixMilliseconds int64   `json:"capturedAtUnixMilliseconds"`
	ProcessedResetRequestID    string  `json:"processedResetRequestId"`
	Error                      string  `json:"error,omitempty"`
}

type codexResourceMonitor struct {
	extensionHostProcessID int
	samplingEnabled        bool
	previousSample         *codexResourcePlatformSample
	uploadedBytesTotal     uint64
	downloadedBytesTotal   uint64
	resetRequestObserved   bool
	lastResetRequestID     string
}

func newCodexResourceMonitor(extensionHostProcessID int) *codexResourceMonitor {
	return &codexResourceMonitor{extensionHostProcessID: extensionHostProcessID}
}

func unavailableCodexResourceMetrics() codexResourceMetrics {
	return codexResourceMetrics{Supported: false}
}

func (monitor *codexResourceMonitor) collectMetrics() (codexResourceMetrics, error) {
	metrics := codexResourceMetrics{
		Supported:               codexResourceMonitoringSupported(),
		SamplingEnabled:         monitor.samplingEnabled,
		ProcessedResetRequestID: monitor.lastResetRequestID,
	}
	if !metrics.Supported || !monitor.samplingEnabled {
		return metrics, nil
	}

	currentSample, err := readCodexResourcePlatformSample(monitor.extensionHostProcessID)
	if err != nil {
		metrics.Error = err.Error()
		return metrics, err
	}
	if monitor.previousSample == nil {
		monitor.previousSample = &currentSample
		metrics.Initializing = true
		metrics.ResidentMemoryBytes = currentSample.ResidentMemoryBytes
		metrics.CapturedAtUnixMilliseconds = currentSample.CapturedAt.UnixMilli()
		return metrics, nil
	}

	metrics, err = calculateCodexResourceMetrics(
		*monitor.previousSample,
		currentSample,
		monitor.uploadedBytesTotal,
		monitor.downloadedBytesTotal,
	)
	if err != nil {
		metrics.Supported = true
		metrics.SamplingEnabled = true
		metrics.Error = err.Error()
		return metrics, err
	}

	monitor.previousSample = &currentSample
	monitor.uploadedBytesTotal = metrics.UploadedBytesTotal
	monitor.downloadedBytesTotal = metrics.DownloadedBytesTotal
	metrics.ProcessedResetRequestID = monitor.lastResetRequestID
	return metrics, nil
}

func (monitor *codexResourceMonitor) observeResetRequestID(resetRequestID string) error {
	if !monitor.resetRequestObserved {
		monitor.resetRequestObserved = true
		monitor.lastResetRequestID = resetRequestID
		return nil
	}
	if resetRequestID == monitor.lastResetRequestID {
		return nil
	}

	monitor.lastResetRequestID = resetRequestID
	monitor.uploadedBytesTotal = 0
	monitor.downloadedBytesTotal = 0
	monitor.previousSample = nil
	if !monitor.samplingEnabled {
		return nil
	}
	initialSample, err := readCodexResourcePlatformSample(monitor.extensionHostProcessID)
	if err != nil {
		return err
	}
	monitor.previousSample = &initialSample
	return nil
}

func (monitor *codexResourceMonitor) setSamplingEnabled(samplingEnabled bool) error {
	if monitor.samplingEnabled == samplingEnabled {
		return nil
	}

	monitor.samplingEnabled = samplingEnabled
	monitor.previousSample = nil
	monitor.uploadedBytesTotal = 0
	monitor.downloadedBytesTotal = 0
	if !samplingEnabled {
		return nil
	}
	if !codexResourceMonitoringSupported() {
		return fmt.Errorf("Codex resource monitoring is not supported on %s", runtime.GOOS)
	}

	initialSample, err := readCodexResourcePlatformSample(monitor.extensionHostProcessID)
	if err != nil {
		return err
	}
	monitor.previousSample = &initialSample
	return nil
}

func calculateCodexResourceMetrics(
	previousSample codexResourcePlatformSample,
	currentSample codexResourcePlatformSample,
	previousUploadedBytesTotal uint64,
	previousDownloadedBytesTotal uint64,
) (codexResourceMetrics, error) {
	elapsedSeconds := currentSample.CapturedAt.Sub(previousSample.CapturedAt).Seconds()
	if elapsedSeconds <= 0 {
		return codexResourceMetrics{}, fmt.Errorf("resource sample elapsed time must be positive: %f", elapsedSeconds)
	}
	if currentSample.SystemCPUClockTicks <= previousSample.SystemCPUClockTicks {
		return codexResourceMetrics{}, fmt.Errorf(
			"system CPU clock did not advance: previous=%d current=%d",
			previousSample.SystemCPUClockTicks,
			currentSample.SystemCPUClockTicks,
		)
	}

	processCPUClockTickDelta, err := processCPUClockTickDelta(previousSample, currentSample)
	if err != nil {
		return codexResourceMetrics{}, err
	}
	uploadedByteDelta, downloadedByteDelta, err := networkByteDeltas(previousSample, currentSample)
	if err != nil {
		return codexResourceMetrics{}, err
	}

	systemCPUClockTickDelta := currentSample.SystemCPUClockTicks - previousSample.SystemCPUClockTicks
	cpuPercent := float64(processCPUClockTickDelta) / float64(systemCPUClockTickDelta) * float64(runtime.NumCPU()) * 100
	uploadBytesPerSecond := uint64(math.Round(float64(uploadedByteDelta) / elapsedSeconds))
	downloadBytesPerSecond := uint64(math.Round(float64(downloadedByteDelta) / elapsedSeconds))
	uploadedBytesTotal := previousUploadedBytesTotal + uploadedByteDelta
	downloadedBytesTotal := previousDownloadedBytesTotal + downloadedByteDelta

	return codexResourceMetrics{
		Supported:                  true,
		SamplingEnabled:            true,
		UploadBytesPerSecond:       uploadBytesPerSecond,
		DownloadBytesPerSecond:     downloadBytesPerSecond,
		UploadedBytesTotal:         uploadedBytesTotal,
		DownloadedBytesTotal:       downloadedBytesTotal,
		ResidentMemoryBytes:        currentSample.ResidentMemoryBytes,
		CPUPercent:                 math.Round(cpuPercent*10) / 10,
		CapturedAtUnixMilliseconds: currentSample.CapturedAt.UnixMilli(),
	}, nil
}

func processCPUClockTickDelta(
	previousSample codexResourcePlatformSample,
	currentSample codexResourcePlatformSample,
) (uint64, error) {
	var totalDelta uint64
	for processKey, currentClockTicks := range currentSample.ProcessCPUClockTicksByKey {
		previousClockTicks, processExistedPreviously := previousSample.ProcessCPUClockTicksByKey[processKey]
		if !processExistedPreviously {
			totalDelta += currentClockTicks
			continue
		}
		if currentClockTicks < previousClockTicks {
			return 0, fmt.Errorf(
				"process CPU clock moved backwards for %s: previous=%d current=%d",
				processKey,
				previousClockTicks,
				currentClockTicks,
			)
		}
		totalDelta += currentClockTicks - previousClockTicks
	}
	return totalDelta, nil
}

func networkByteDeltas(
	previousSample codexResourcePlatformSample,
	currentSample codexResourcePlatformSample,
) (uint64, uint64, error) {
	var uploadedByteDelta uint64
	var downloadedByteDelta uint64
	for connectionKey, currentCounters := range currentSample.NetworkConnectionsByKey {
		previousCounters, connectionExistedPreviously := previousSample.NetworkConnectionsByKey[connectionKey]
		if !connectionExistedPreviously {
			uploadedByteDelta += currentCounters.UploadedBytes
			downloadedByteDelta += currentCounters.DownloadedBytes
			continue
		}
		if currentCounters.UploadedBytes < previousCounters.UploadedBytes {
			return 0, 0, fmt.Errorf("uploaded byte counter moved backwards for connection %s", connectionKey)
		}
		if currentCounters.DownloadedBytes < previousCounters.DownloadedBytes {
			return 0, 0, fmt.Errorf("downloaded byte counter moved backwards for connection %s", connectionKey)
		}
		uploadedByteDelta += currentCounters.UploadedBytes - previousCounters.UploadedBytes
		downloadedByteDelta += currentCounters.DownloadedBytes - previousCounters.DownloadedBytes
	}
	return uploadedByteDelta, downloadedByteDelta, nil
}
