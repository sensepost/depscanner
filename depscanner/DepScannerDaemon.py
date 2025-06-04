from depscanner import DepScanner
import threading
import logging

class DepScannerDaemon:
    def __init__(self, dep_scanner: DepScanner = None, logger: logging.Logger = None):
        self.dep_scanner = dep_scanner
        self.status = "Idle"  # Status of the daemon
        self.thread = None
        self.running = False
        self.logger = logger if logger else logging

    def start(self):
        """Start the daemon in a separate thread."""
        if self.thread is None or not self.thread.is_alive():
            self.logger.error('Initiating DepScanner')
            self.running = True
            self.status = "Running"
            self.thread = threading.Thread(target=self._run)
            self.thread.daemon = True  # Ensure the thread exits when the main program exits
            self.thread.start()
        else:
            self.logger.error('Scan is alredy running')

    def _run(self):
        """Run the DepScanner scan process."""
        try:
            self.dep_scanner.scan()
            self.logger.info("Completed")
            self.status = "Completed"
        except Exception as e:
            self.logger.error(f"Error: {str(e)}")
            self.status = f"Error: {str(e)}"
        finally:
            self.running = False

    def stop(self):
        """Stop the daemon."""
        self.running = False
        self.logger.info("FAKE: Stopping the scan")
        self.status = "FAKE: Stopped"

    def get_progress(self):
        """Get the current progress of the scan."""
        if self.dep_scanner:
            p = self.dep_scanner.get_scan_progress()
            logging.debug(f"Progress: {p}")
            return p
        return None

    def get_status(self):
        """Get the current status of the daemon."""
        return self.status
    
    def authenticated_as(self):
        if self.dep_scanner:
            return self.dep_scanner.is_user_authenticated()
        return None
