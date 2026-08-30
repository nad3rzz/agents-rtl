package main

import "testing"

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
