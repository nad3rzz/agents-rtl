package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestValidateRequiredDevtoolsPortsRejectsMissingPorts(t *testing.T) {
	err := validateRequiredDevtoolsPorts(nil)
	if err == nil {
		t.Fatal("expected missing DevTools ports to fail")
	}
	if err.Error() != "at least one --port is required" {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestValidateRequiredDevtoolsPortsAcceptsExplicitPorts(t *testing.T) {
	err := validateRequiredDevtoolsPorts(portFlags{43127, 43128})
	if err != nil {
		t.Fatalf("expected explicit DevTools ports to pass: %v", err)
	}
}

func TestValidateResourceMonitorArgumentsAcceptsDisabledMonitor(t *testing.T) {
	err := validateResourceMonitorArguments(portFlags{43127}, 0, 0)
	if err != nil {
		t.Fatalf("expected omitted resource monitor arguments to pass: %v", err)
	}
}

func TestValidateResourceMonitorArgumentsRequiresCompletePair(t *testing.T) {
	err := validateResourceMonitorArguments(portFlags{43127}, 43127, 0)
	if err == nil {
		t.Fatal("expected incomplete resource monitor arguments to fail")
	}
}

func TestValidateResourceMonitorArgumentsRequiresWatchedPort(t *testing.T) {
	err := validateResourceMonitorArguments(portFlags{43127}, 43128, 900)
	if err == nil {
		t.Fatal("expected an unwatched resource monitor port to fail")
	}
}

func TestValidateResourceMonitorArgumentsAcceptsExplicitMonitor(t *testing.T) {
	err := validateResourceMonitorArguments(portFlags{43127, 43128}, 43127, 900)
	if err != nil {
		t.Fatalf("expected complete resource monitor arguments to pass: %v", err)
	}
}

func TestValidateSessionDoctorScriptPathAcceptsDisabledIntegration(t *testing.T) {
	if err := validateSessionDoctorScriptPath(""); err != nil {
		t.Fatalf("expected disabled session Doctor integration to pass: %v", err)
	}
}

func TestValidateSessionDoctorScriptPathRejectsRelativePath(t *testing.T) {
	err := validateSessionDoctorScriptPath("tools/codex_session_doctor.py")
	if err == nil {
		t.Fatal("expected relative session Doctor path to fail")
	}
}

func TestValidateSessionDoctorScriptPathRejectsMissingFile(t *testing.T) {
	err := validateSessionDoctorScriptPath(filepath.Join(t.TempDir(), "missing.py"))
	if err == nil {
		t.Fatal("expected missing session Doctor script to fail")
	}
}

func TestValidateSessionDoctorScriptPathAcceptsRegularFile(t *testing.T) {
	scriptPath := filepath.Join(t.TempDir(), "codex_session_doctor.py")
	if err := os.WriteFile(scriptPath, []byte("print('doctor')\n"), 0o600); err != nil {
		t.Fatalf("write session Doctor fixture: %v", err)
	}
	if err := validateSessionDoctorScriptPath(scriptPath); err != nil {
		t.Fatalf("expected regular session Doctor script to pass: %v", err)
	}
}
