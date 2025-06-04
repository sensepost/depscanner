function addEventListeners() {
  // run.html: Add event listener for the list files dropdown
  const fileTypeSelect = document.getElementById("file_type");
  if (fileTypeSelect) {
    document.getElementById("file_type").addEventListener("change", function () {
      const fileType = this.value;
      fetch("/get-files", {
          method: "POST",
          headers: {
              "Content-Type": "application/json",
          },
          body: JSON.stringify({ file_type: fileType }),
      })
          .then((response) => response.json())
          .then((data) => {
              const fileList = document.getElementById("fileList");
              fileList.innerHTML = ""; // Clear the table body

              data.files.forEach((file) => {
                  const row = document.createElement("tr");

                  // Create table cells
                  const nameCell = document.createElement("td");
                  nameCell.textContent = file.name;

                  const sizeCell = document.createElement("td");
                  sizeCell.textContent = file.size;

                  const dateCell = document.createElement("td");
                  dateCell.textContent = file.date;

                  const actionCell = document.createElement("td");

                  // Create action container
                  const actionContainer = document.createElement("div");
                  actionContainer.className = "d-flex gap-2"; // Flexbox container with spacing between buttons

                  // Green "Copy File Path" Button
                  const copyButton = document.createElement("button");
                  copyButton.type = "button";
                  copyButton.title = "Select this file as source";
                  copyButton.className = "btn btn-success btn-sm"; // Green button
                  copyButton.innerHTML = '<i class="bi bi-bullseye"></i>';
                  copyButton.onclick = () => selectSourceFile(file.path);
                  actionContainer.appendChild(copyButton);

                  // Delete Button
                  const deleteButton = document.createElement("button");
                  deleteButton.type = "button";
                  deleteButton.title = "Delete File";
                  deleteButton.className = "btn btn-danger btn-sm";
                  deleteButton.innerHTML = '<i class="bi bi-trash"></i>';
                  deleteButton.onclick = () => deleteFile(file.path);
                  actionContainer.appendChild(deleteButton);

                  // Append the action container to the action cell
                  actionCell.appendChild(actionContainer);

                  // Append cells to the row
                  row.appendChild(nameCell);
                  row.appendChild(sizeCell);
                  row.appendChild(dateCell);
                  row.appendChild(actionCell);

                  // Append the row to the table body
                  fileList.appendChild(row);
              });
          })
          .catch((error) => console.error("Error fetching files:", error));
    });
  }
  else {
    console.error("fileTypeSelect element not found");
  }
}

function updateProgressBar() {
  const runButton = document.getElementById("run-button");
  const scanStatus = document.getElementById("scan-status");
  const progressBar = document.getElementById("progress-bar");

  function updateScanProgress() {
    // Get the progress, percentage to present it in the progress bar
    fetch("/scan/progress")
      .then((response) => {
        if (!response.ok) {
          throw new Error("Failed to fetch scan progress");
        }
        return response.json();
      })
      .then((data) => {
        if (data && typeof data.total !== "undefined") {
          if (data.total > 0) {
            // Show the scan status and update the progress bar
            scanStatus.style.display = "block";
            progressBar.style.width = `${data.percentage}%`;
            progressBar.setAttribute("aria-valuenow", data.percentage);
            progressBar.textContent = `${data.percentage}%`;

            // Disable the "Run" button while the scan is running
            runButton.disabled = true;

            // If the scan is complete, re-enable the "Run" button
            if (data.percentage === 100) {
              runButton.disabled = false;
              scanStatus.style.display = "none";
            }
          }
        }
      })
      .catch((error) => {
        console.error("Error fetching scan progress:", error);
      });

      // Get the status to replace the run button text
      fetch("/scan/status")
        .then((response) => {
          if (!response.ok) {
            throw new Error("Failed to fetch run status");
          }
          return response.text(); // Get the response as plain text
        })
        .then((statusText) => {
          // Replace the button text with the response text
          if (statusText.trim() == '"Running"') {
            runButton.textContent = "Running";
            // Disable the button
            runButton.disabled = true;
          }
        })
        .catch((error) => {
          console.error("Error fetching run status:", error);
        });
  }

  // Periodically check the scan progress every 5 seconds
  setInterval(updateScanProgress, 5000);

  // Check progress immediately on page load
  updateScanProgress();
}

function addRunButtonClickedListener(){
  // Add onclick listener to the "Run" button
  const runButton = document.getElementById("run-button");
  if (runButton) { 

  }
}

function validateInputsForRunButton() {
  const githubTokenInput = document.getElementById("githubToken");
  const fileNameInput = document.getElementById("file_name");
  const submitButton = document.querySelector("button[type='submit']");

  function validateInputs() {
    // Check if all inputs are populated
    const isValid =
      githubTokenInput.value.trim() !== "" &&
      fileNameInput.value.trim() !== "";

    // Enable or disable the submit button based on validation
    submitButton.disabled = !isValid;
  }

  // Add event listeners to validate inputs on change
  githubTokenInput.addEventListener("input", validateInputs);
  fileNameInput.addEventListener("input", validateInputs);

  // Validate inputs on load to ensure the button is enabled if fields are already filled
  validateInputs();
}

function togglePassword() {
    const input = document.getElementById('githubToken');
    input.type = input.type === 'password' ? 'text' : 'password';
}

function deleteFile(filePath) {
  // Get the selected file name
  fetch("/delete-file", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ file_path: filePath }),
  })
    .then((response) => response.json())
    .then((data) => {
      if (data.success) {
        alert("File deleted successfully.");
        updateFileList();
      } else {
        alert("Error deleting file.");
      }
    })
    .catch((error) => console.error("Error deleting file:", error));
}

function selectSourceFile(filePath) {
  const selectedFileInput = document.getElementById("file_name");
  if (selectedFileInput) {
      selectedFileInput.value = filePath; // Set the file path to the input field
  }
}

function loadSessionSettings(){
  const formFields = ["file_type", "numStars", "file_name", "githubToken", "discordWebhook", "forceRefresh"];
    
  // Populate fields from sessionStorage if data exists
  formFields.forEach(field => {
      const element = document.getElementById(field);
      if (element && sessionStorage.getItem(field)) {
          if (element.type === "checkbox") {
              element.checked = sessionStorage.getItem(field) === "true";
          } else {
              element.value = sessionStorage.getItem(field);
          }
      }
  });

  // Add event listener to the form submit button
  const submitButton = document.querySelector("button[type='submit']");
  submitButton.addEventListener("click", function (event) {
      event.preventDefault(); // Prevent form submission for now

      // Ask the user if they want to save the settings
      if (confirm("Do you want to save these settings for future runs?")) {
          formFields.forEach(field => {
              const element = document.getElementById(field);
              if (element) {
                  if (element.type === "checkbox") {
                      sessionStorage.setItem(field, element.checked);
                  } else {
                      sessionStorage.setItem(field, element.value);
                  }
              }
          });
      }

      // Submit the form after saving settings
      event.target.closest("form").submit();
  });
}

// main 
// When the dom is loaded, add event listeners
document.addEventListener("DOMContentLoaded", function () {
  loadSessionSettings();
  addEventListeners();
  validateInputsForRunButton();
  updateProgressBar();
  addRunButtonClickedListener();
});