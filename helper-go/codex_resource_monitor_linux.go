//go:build linux

package main

import (
	"bufio"
	"bytes"
	"context"
	"fmt"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

const (
	linuxProcRootPath                = "/proc"
	linuxSystemCPUClockFieldCount    = 8
	linuxSSCommandTimeout            = 2 * time.Second
	linuxSSScannerInitialBufferBytes = 64 * 1024
	linuxSSScannerMaximumBufferBytes = 1024 * 1024
)

var linuxSSProcessIDPattern = regexp.MustCompile(`pid=([0-9]+)`)
var linuxSSSocketInodePattern = regexp.MustCompile(`ino:([0-9]+)`)

type linuxProcessStat struct {
	CPUClockTicks uint64
	StartTime     uint64
}

func codexResourceMonitoringSupported() bool {
	return true
}

func readCodexResourcePlatformSample(extensionHostProcessID int) (codexResourcePlatformSample, error) {
	codexAppServerProcessID, err := findCodexAppServerProcessID(extensionHostProcessID)
	if err != nil {
		return codexResourcePlatformSample{}, err
	}
	monitoredProcessIDs, err := collectLinuxProcessSubtree(codexAppServerProcessID)
	if err != nil {
		return codexResourcePlatformSample{}, err
	}

	processCPUClockTicksByKey := make(map[string]uint64, len(monitoredProcessIDs))
	var residentMemoryBytes uint64
	monitoredProcessIDSet := make(map[int]bool, len(monitoredProcessIDs))
	for _, processID := range monitoredProcessIDs {
		monitoredProcessIDSet[processID] = true
		processStat, err := readLinuxProcessStat(processID)
		if err != nil {
			return codexResourcePlatformSample{}, err
		}
		processKey := fmt.Sprintf("%d:%d", processID, processStat.StartTime)
		processCPUClockTicksByKey[processKey] = processStat.CPUClockTicks

		processResidentMemoryBytes, err := readLinuxProcessResidentMemoryBytes(processID)
		if err != nil {
			return codexResourcePlatformSample{}, err
		}
		residentMemoryBytes += processResidentMemoryBytes
	}

	systemCPUClockTicks, err := readLinuxSystemCPUClockTicks()
	if err != nil {
		return codexResourcePlatformSample{}, err
	}
	networkConnectionsByKey, err := readLinuxNetworkConnectionCounters(monitoredProcessIDSet)
	if err != nil {
		return codexResourcePlatformSample{}, err
	}

	return codexResourcePlatformSample{
		CapturedAt:                time.Now(),
		SystemCPUClockTicks:       systemCPUClockTicks,
		ProcessCPUClockTicksByKey: processCPUClockTicksByKey,
		ResidentMemoryBytes:       residentMemoryBytes,
		NetworkConnectionsByKey:   networkConnectionsByKey,
	}, nil
}

func findCodexAppServerProcessID(extensionHostProcessID int) (int, error) {
	childProcessIDs, err := readLinuxChildProcessIDs(extensionHostProcessID)
	if err != nil {
		return 0, fmt.Errorf("read Extension Host children for PID %d: %w", extensionHostProcessID, err)
	}

	matchingProcessIDs := []int{}
	for _, childProcessID := range childProcessIDs {
		processName, err := readLinuxProcessName(childProcessID)
		if err != nil {
			return 0, err
		}
		if processName != "codex" {
			continue
		}
		commandArguments, err := readLinuxProcessCommandArguments(childProcessID)
		if err != nil {
			return 0, err
		}
		if containsExactString(commandArguments, "app-server") {
			matchingProcessIDs = append(matchingProcessIDs, childProcessID)
		}
	}

	if len(matchingProcessIDs) != 1 {
		return 0, fmt.Errorf(
			"expected exactly one Codex app-server child of Extension Host PID %d, found %d: %v",
			extensionHostProcessID,
			len(matchingProcessIDs),
			matchingProcessIDs,
		)
	}
	return matchingProcessIDs[0], nil
}

func collectLinuxProcessSubtree(rootProcessID int) ([]int, error) {
	processIDs := []int{}
	pendingProcessIDs := []int{rootProcessID}
	visitedProcessIDs := map[int]bool{}
	for len(pendingProcessIDs) > 0 {
		processID := pendingProcessIDs[0]
		pendingProcessIDs = pendingProcessIDs[1:]
		if visitedProcessIDs[processID] {
			continue
		}
		visitedProcessIDs[processID] = true
		processIDs = append(processIDs, processID)

		childProcessIDs, err := readLinuxChildProcessIDs(processID)
		if err != nil {
			return nil, fmt.Errorf("read child processes for PID %d: %w", processID, err)
		}
		pendingProcessIDs = append(pendingProcessIDs, childProcessIDs...)
	}
	return processIDs, nil
}

func readLinuxChildProcessIDs(processID int) ([]int, error) {
	childrenPath := filepath.Join(
		linuxProcRootPath,
		strconv.Itoa(processID),
		"task",
		strconv.Itoa(processID),
		"children",
	)
	childrenBytes, err := os.ReadFile(childrenPath)
	if err != nil {
		return nil, err
	}

	childProcessIDs := []int{}
	for _, childProcessIDText := range strings.Fields(string(childrenBytes)) {
		childProcessID, err := strconv.Atoi(childProcessIDText)
		if err != nil {
			return nil, fmt.Errorf("invalid child process ID %q in %s: %w", childProcessIDText, childrenPath, err)
		}
		childProcessIDs = append(childProcessIDs, childProcessID)
	}
	return childProcessIDs, nil
}

func readLinuxProcessName(processID int) (string, error) {
	processNamePath := filepath.Join(linuxProcRootPath, strconv.Itoa(processID), "comm")
	processNameBytes, err := os.ReadFile(processNamePath)
	if err != nil {
		return "", fmt.Errorf("read process name for PID %d: %w", processID, err)
	}
	return strings.TrimSpace(string(processNameBytes)), nil
}

func readLinuxProcessCommandArguments(processID int) ([]string, error) {
	commandLinePath := filepath.Join(linuxProcRootPath, strconv.Itoa(processID), "cmdline")
	commandLineBytes, err := os.ReadFile(commandLinePath)
	if err != nil {
		return nil, fmt.Errorf("read command line for PID %d: %w", processID, err)
	}
	trimmedCommandLine := bytes.TrimRight(commandLineBytes, "\x00")
	if len(trimmedCommandLine) == 0 {
		return nil, fmt.Errorf("process command line is empty for PID %d", processID)
	}
	return strings.Split(string(trimmedCommandLine), "\x00"), nil
}

func containsExactString(values []string, expectedValue string) bool {
	for _, value := range values {
		if value == expectedValue {
			return true
		}
	}
	return false
}

func readLinuxProcessStat(processID int) (linuxProcessStat, error) {
	statPath := filepath.Join(linuxProcRootPath, strconv.Itoa(processID), "stat")
	statBytes, err := os.ReadFile(statPath)
	if err != nil {
		return linuxProcessStat{}, fmt.Errorf("read process stat for PID %d: %w", processID, err)
	}
	return parseLinuxProcessStat(processID, string(statBytes))
}

func parseLinuxProcessStat(processID int, statText string) (linuxProcessStat, error) {
	commandEndIndex := strings.LastIndex(statText, ")")
	if commandEndIndex == -1 || commandEndIndex+2 >= len(statText) {
		return linuxProcessStat{}, fmt.Errorf("invalid /proc stat format for PID %d", processID)
	}
	fieldsAfterCommand := strings.Fields(statText[commandEndIndex+2:])
	const userCPUClockTickFieldIndex = 11
	const systemCPUClockTickFieldIndex = 12
	const processStartTimeFieldIndex = 19
	if len(fieldsAfterCommand) <= processStartTimeFieldIndex {
		return linuxProcessStat{}, fmt.Errorf("incomplete /proc stat for PID %d", processID)
	}

	userCPUClockTicks, err := strconv.ParseUint(fieldsAfterCommand[userCPUClockTickFieldIndex], 10, 64)
	if err != nil {
		return linuxProcessStat{}, fmt.Errorf("invalid user CPU ticks for PID %d: %w", processID, err)
	}
	systemCPUClockTicks, err := strconv.ParseUint(fieldsAfterCommand[systemCPUClockTickFieldIndex], 10, 64)
	if err != nil {
		return linuxProcessStat{}, fmt.Errorf("invalid system CPU ticks for PID %d: %w", processID, err)
	}
	processStartTime, err := strconv.ParseUint(fieldsAfterCommand[processStartTimeFieldIndex], 10, 64)
	if err != nil {
		return linuxProcessStat{}, fmt.Errorf("invalid start time for PID %d: %w", processID, err)
	}

	return linuxProcessStat{
		CPUClockTicks: userCPUClockTicks + systemCPUClockTicks,
		StartTime:     processStartTime,
	}, nil
}

func readLinuxProcessResidentMemoryBytes(processID int) (uint64, error) {
	statmPath := filepath.Join(linuxProcRootPath, strconv.Itoa(processID), "statm")
	statmBytes, err := os.ReadFile(statmPath)
	if err != nil {
		return 0, fmt.Errorf("read process memory for PID %d: %w", processID, err)
	}
	statmFields := strings.Fields(string(statmBytes))
	if len(statmFields) < 2 {
		return 0, fmt.Errorf("incomplete process memory data for PID %d", processID)
	}
	residentMemoryPages, err := strconv.ParseUint(statmFields[1], 10, 64)
	if err != nil {
		return 0, fmt.Errorf("invalid resident memory pages for PID %d: %w", processID, err)
	}
	pageSizeBytes := uint64(os.Getpagesize())
	if residentMemoryPages > math.MaxUint64/pageSizeBytes {
		return 0, fmt.Errorf("resident memory size overflow for PID %d", processID)
	}
	return residentMemoryPages * pageSizeBytes, nil
}

func readLinuxSystemCPUClockTicks() (uint64, error) {
	statBytes, err := os.ReadFile(filepath.Join(linuxProcRootPath, "stat"))
	if err != nil {
		return 0, fmt.Errorf("read system CPU stat: %w", err)
	}
	firstLine, _, _ := strings.Cut(string(statBytes), "\n")
	fields := strings.Fields(firstLine)
	if len(fields) < linuxSystemCPUClockFieldCount+1 || fields[0] != "cpu" {
		return 0, fmt.Errorf("invalid aggregate CPU line in /proc/stat: %q", firstLine)
	}

	var totalClockTicks uint64
	for _, field := range fields[1 : linuxSystemCPUClockFieldCount+1] {
		clockTicks, err := strconv.ParseUint(field, 10, 64)
		if err != nil {
			return 0, fmt.Errorf("invalid system CPU clock value %q: %w", field, err)
		}
		totalClockTicks += clockTicks
	}
	return totalClockTicks, nil
}

func readLinuxNetworkConnectionCounters(monitoredProcessIDs map[int]bool) (map[string]codexResourceConnectionCounters, error) {
	commandContext, cancelCommand := context.WithTimeout(context.Background(), linuxSSCommandTimeout)
	defer cancelCommand()
	commandOutput, err := exec.CommandContext(commandContext, "ss", "-tinpeH", "state", "established").Output()
	if err != nil {
		if commandContext.Err() != nil {
			return nil, fmt.Errorf("ss timed out after %s: %w", linuxSSCommandTimeout, commandContext.Err())
		}
		return nil, fmt.Errorf("read TCP connection counters with ss: %w", err)
	}
	return parseLinuxSSNetworkConnectionCounters(commandOutput, monitoredProcessIDs)
}

func parseLinuxSSNetworkConnectionCounters(
	commandOutput []byte,
	monitoredProcessIDs map[int]bool,
) (map[string]codexResourceConnectionCounters, error) {
	connectionsByKey := map[string]codexResourceConnectionCounters{}
	pendingConnectionKey := ""
	scanner := bufio.NewScanner(bytes.NewReader(commandOutput))
	scanner.Buffer(make([]byte, linuxSSScannerInitialBufferBytes), linuxSSScannerMaximumBufferBytes)
	for scanner.Scan() {
		line := scanner.Text()
		if line == "" {
			continue
		}
		if line[0] != ' ' && line[0] != '\t' {
			connectionKey, belongsToMonitoredProcess, err := linuxSSConnectionKey(line, monitoredProcessIDs)
			if err != nil {
				return nil, err
			}
			if belongsToMonitoredProcess {
				pendingConnectionKey = connectionKey
			} else {
				pendingConnectionKey = ""
			}
			continue
		}
		if pendingConnectionKey == "" {
			continue
		}

		connectionCounters, err := parseLinuxSSConnectionCounterLine(line)
		if err != nil {
			return nil, fmt.Errorf("parse TCP counters for connection %s: %w", pendingConnectionKey, err)
		}
		if _, exists := connectionsByKey[pendingConnectionKey]; exists {
			return nil, fmt.Errorf("duplicate TCP connection inode: %s", pendingConnectionKey)
		}
		connectionsByKey[pendingConnectionKey] = connectionCounters
		pendingConnectionKey = ""
	}
	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("scan ss output: %w", err)
	}
	if pendingConnectionKey != "" {
		return nil, fmt.Errorf("missing TCP_INFO counters for connection %s", pendingConnectionKey)
	}
	return connectionsByKey, nil
}

func linuxSSConnectionKey(statusLine string, monitoredProcessIDs map[int]bool) (string, bool, error) {
	matchingProcessID := 0
	for _, match := range linuxSSProcessIDPattern.FindAllStringSubmatch(statusLine, -1) {
		processID, err := strconv.Atoi(match[1])
		if err != nil {
			return "", false, fmt.Errorf("invalid process ID %q in ss output: %w", match[1], err)
		}
		if monitoredProcessIDs[processID] {
			matchingProcessID = processID
			break
		}
	}
	if matchingProcessID == 0 {
		return "", false, nil
	}
	inodeMatch := linuxSSSocketInodePattern.FindStringSubmatch(statusLine)
	if len(inodeMatch) != 2 {
		return "", true, fmt.Errorf("monitored TCP connection is missing its socket inode: %q", statusLine)
	}
	return fmt.Sprintf("%d:%s", matchingProcessID, inodeMatch[1]), true, nil
}

func parseLinuxSSConnectionCounterLine(counterLine string) (codexResourceConnectionCounters, error) {
	uploadedBytes, uploadedBytesFound, err := parseLinuxSSUintField(counterLine, "bytes_acked:")
	if err != nil {
		return codexResourceConnectionCounters{}, err
	}
	downloadedBytes, downloadedBytesFound, err := parseLinuxSSUintField(counterLine, "bytes_received:")
	if err != nil {
		return codexResourceConnectionCounters{}, err
	}
	if !uploadedBytesFound || !downloadedBytesFound {
		return codexResourceConnectionCounters{}, fmt.Errorf(
			"required counters are missing: bytes_acked=%t bytes_received=%t",
			uploadedBytesFound,
			downloadedBytesFound,
		)
	}
	return codexResourceConnectionCounters{
		UploadedBytes:   uploadedBytes,
		DownloadedBytes: downloadedBytes,
	}, nil
}

func parseLinuxSSUintField(line string, fieldPrefix string) (uint64, bool, error) {
	for _, field := range strings.Fields(line) {
		if !strings.HasPrefix(field, fieldPrefix) {
			continue
		}
		valueText := strings.TrimPrefix(field, fieldPrefix)
		value, err := strconv.ParseUint(valueText, 10, 64)
		if err != nil {
			return 0, false, fmt.Errorf("invalid %s value %q: %w", fieldPrefix, valueText, err)
		}
		return value, true, nil
	}
	return 0, false, nil
}
