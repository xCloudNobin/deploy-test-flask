(() => {
  document.documentElement.classList.add("js");

  const confirmDelete = (target) => {
    return window.confirm(`Are you sure you want to delete ${target}?`);
  };

  const confirmStatus = (title) => {
    return window.confirm(`Change the status of "${title}"?`);
  };

  const selects = document.querySelectorAll("[data-autosubmit]");
  selects.forEach((select) => {
    select.addEventListener("change", () => {
      const form = select.closest("[data-task-status]");
      if (form) {
        form.requestSubmit();
      }
    });
  });
})();