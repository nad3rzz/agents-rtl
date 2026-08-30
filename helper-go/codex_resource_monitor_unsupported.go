//go:build !linux

package main

import (
	"fmt"
	"runtime"
)

func codexResourceMonitoringSupported() bool {
	return false
}

func readCodexResourcePlatformSample(extensionHostProcessID int) (codexResourcePlatformSample, error) {
	return codexResourcePlatformSample{}, fmt.Errorf(
		"Codex resource monitoring is not supported on %s for Extension Host PID %d",
		runtime.GOOS,
		extensionHostProcessID,
	)
}
