let currentLogFile = undefined; // Track the currently selected log file
let logOffset = 0;

// Select a log file and start fetching its content
function selectLogFile(fileName) {
  // Clear the log container
  const logContainer = document.getElementById("log-container");
  logContainer.value = ''; // Clear the log container
  logOffset = 0; // Reset the offset

  currentLogFile = fileName;
  // Color the row of the selected file
  const logFilesList = document.querySelectorAll('#log-file-list li');
  logFilesList.forEach(item => {
    item.style.fontWeight = (item.textContent === fileName) ? 'bold' : 'normal';
  });
  fetchLogContent(); // Fetch the initial content

  // Enable the download button
  const downloadButton = document.getElementById("download-log-button");
  downloadButton.disabled = false;
}

// Fetch logs from the server
function fetchLogContent() {
  fetch(`/logs/tail?offset=${logOffset}&file=${currentLogFile}`)
    .then(response => response.json())
    .then(data => {
      const logContainer = document.getElementById("log-container");
      logContainer.value += data.content; // Append new log content
      logContainer.scrollTop = logContainer.scrollHeight; // Auto-scroll to the bottom
      logOffset = data.new_offset; // Update the offset for the next request
    })
    .catch(error => console.error("Error fetching logs:", error));
}

// Fetch the list of log files
function fetchLogFiles() {
  fetch('/logs/files')
    .then(response => response.json())
    .then(data => {
      const logFilesList = document.getElementById('log-files');
      logFilesList.innerHTML = ''; // Clear the list
      data.files.forEach(file => {
        const listItem = document.createElement('li');
        listItem.textContent = file.name;
        listItem.onclick = () => selectLogFile(file.name);
        logFilesList.appendChild(listItem);
      });
    })
    .catch(error => console.error('Error fetching log files:', error));
}

// Download the selected log file
function downloadLogFile() {
  if (!currentLogFile) {
    alert("No log file selected!");
    return;
  }

  // Fetch the log file content
  fetch(`/logs/download?file=${encodeURIComponent(currentLogFile)}`)
    .then((response) => {
      if (!response.ok) {
        throw new Error("Failed to download log file");
      }
      return response.blob();
    })
    .then((blob) => {
      // Create a temporary link to download the file
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = currentLogFile; // Set the file name for download
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url); // Clean up the URL object
    })
    .catch((error) => {
      console.error("Error downloading log file:", error);
    });
}