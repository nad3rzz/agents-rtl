//go:build linux

package main

import (
	"fmt"
	"os"

	"golang.org/x/sys/unix"
)

func acquireCodexPreferencesFileLock(lockPath string) (*os.File, error) {
	lockFile, err := os.OpenFile(lockPath, os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	if err := unix.Flock(int(lockFile.Fd()), unix.LOCK_EX); err != nil {
		closeErr := lockFile.Close()
		if closeErr != nil {
			return nil, fmt.Errorf("lock Codex preferences: %w; close lock file: %v", err, closeErr)
		}
		return nil, err
	}
	return lockFile, nil
}

func releaseCodexPreferencesFileLock(lockFile *os.File) error {
	unlockErr := unix.Flock(int(lockFile.Fd()), unix.LOCK_UN)
	closeErr := lockFile.Close()
	if unlockErr != nil {
		if closeErr != nil {
			return fmt.Errorf("unlock Codex preferences: %w; close lock file: %v", unlockErr, closeErr)
		}
		return unlockErr
	}
	return closeErr
}
