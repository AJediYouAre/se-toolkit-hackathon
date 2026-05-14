// =============================================
// Recipe Rotator — Client-side JavaScript
// =============================================

/**
 * Fetch a random recipe via API and inject it into the page.
 */
async function loadRandom() {
    const msg = document.getElementById('random-msg');
    const result = document.getElementById('random-result');
    msg.textContent = '⏳ Loading...';
    result.innerHTML = '';

    try {
        const resp = await fetch('/api/recipes/random');
        if (!resp.ok) {
            msg.textContent = '';
            result.innerHTML = '<div class="alert alert-danger">Failed to load recipe</div>';
            return;
        }
        const data = await resp.json();
        if (!data) {
            msg.textContent = '';
            result.innerHTML = '<div class="alert alert-warning">No recipes yet</div>';
            return;
        }

        const ingredients = data.ingredients
            ? data.ingredients.split('\n').filter(l => l.trim()).map(l => `<li>${l.trim()}</li>`).join('')
            : '';

        msg.textContent = '';
        const newCard = document.createElement('div');
        newCard.innerHTML = `
            <div class="card recipe-card">
                <div class="card-body">
                    <div class="content">
                        <h4 class="card-title">${data.title}</h4>
                        <div class="scrollable">
                            <h6 class="text-muted mt-3">🥕 Ingredients</h6>
                            <ul>${ingredients}</ul>
                            <h6 class="text-muted mt-3">👨‍🍳 Instructions</h6>
                            <p style="white-space: pre-line;">${data.instructions || ''}</p>
                        </div>
                        <div class="d-flex justify-content-between align-items-center mt-3">
                            <a href="/recipes/${data.id}" class="btn btn-outline-info btn-sm">Details</a>
                            <span class="text-muted small">Added: ${data.created_at ? new Date(data.created_at).toISOString().slice(0, 10) : ''}</span>
                        </div>
                    </div>
                    <div class="picture">
                        ${data.image_url
                            ? `<img src="${data.image_url}" alt="${data.title}">`
                            : '<div class="picture-placeholder">📷</div>'}
                    </div>
                </div>
            </div>`;
        result.appendChild(newCard.firstElementChild);
        // Scroll to the bottom of the new card
        result.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (e) {
        msg.textContent = '';
        result.innerHTML = '<div class="alert alert-danger">Error loading recipe</div>';
    }
}

/**
 * Delete a recipe after confirmation.
 */
async function deleteRecipe(id) {
    if (!confirm('Delete this recipe? This cannot be undone.')) return;
    try {
        const resp = await fetch(`/api/recipes/${id}`, { method: 'DELETE' });
        if (resp.ok) {
            window.location.href = '/recipes';
        } else {
            alert('Failed to delete recipe');
        }
    } catch (e) {
        alert('Error deleting recipe');
    }
}
