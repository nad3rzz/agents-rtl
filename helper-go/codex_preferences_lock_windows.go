//go:build windows

package main

import (
	"fmt"
	"os"

	"golang.org/x/sys/windows"
)

func acquireCodexPreferencesFileLock(lockPath string) (*os.File, error) {
	lockFile, err := os.OpenFile(lockPath, os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	overlapped := windows.Overlapped{}
	if err := windows.LockFileEx(
		windows.Handle(lockFile.Fd()),
		windows.LOCKFILE_EXCLUSIVE_LOCK,
		0,
		1,
		0,
		&overlapped,
	); err != nil {
		closeErr := lockFile.Close()
		if closeErr != nil {
			return nil, fmt.Errorf("lock Codex preferences: %w; close lock file: %v", err, closeErr)
		}
		return nil, err
	}
	return lockFile, nil
}

func releaseCodexPreferencesFileLock(lockFile *os.File) error {
	overlapped := windows.Overlapped{}
	unlockErr := windows.UnlockFileEx(windows.Handle(lockFile.Fd()), 0, 1, 0, &overlapped)
	closeErr := lockFile.Close()
	if unlockErr != nil {
		if closeErr != nil {
			return fmt.Errorf("unlock Codex preferences: %w; close lock file: %v", unlockErr, closeErr)
		}
		return unlockErr
	}
	return closeErr
}
