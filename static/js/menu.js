(() => {
    const burger = document.querySelector("[data-nav-burger]");
    const menu = document.querySelector("[data-nav-burger-menu]");
    if (!burger || !menu) return;

    const ensureBackdrop = () => {
        let backdrop = document.querySelector(".header-backdrop");
        if (backdrop) return backdrop;
        backdrop = document.createElement("button");
        backdrop.type = "button";
        backdrop.className = "header-backdrop";
        backdrop.setAttribute("aria-label", "Menyuni yopish");
        backdrop.addEventListener("click", () => setOpen(false));
        document.body.append(backdrop);
        return backdrop;
    };

    const setOpen = (open) => {
        menu.classList.toggle("nav-open", open);
        burger.classList.toggle("is-active", open);
        burger.setAttribute("aria-expanded", String(open));
        burger.setAttribute("aria-label", open ? "Menyuni yopish" : "Menyuni ochish");
        const backdrop = ensureBackdrop();
        backdrop.classList.toggle("is-open", open);
        document.body.classList.toggle("modal-open", open);
    };

    burger.addEventListener("click", () => {
        setOpen(menu.classList.contains("nav-open") === false);
    });

    // Menyu havolasi bosilganda menyuni yopish (mobil navigatsiya)
    menu.addEventListener("click", (event) => {
        if (event.target.closest("a")) setOpen(false);
    });

    document.addEventListener("click", (event) => {
        if (
            burger.getAttribute("aria-expanded") === "true" &&
            !burger.contains(event.target) &&
            !menu.contains(event.target)
        ) {
            setOpen(false);
        }
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && burger.getAttribute("aria-expanded") === "true") {
            setOpen(false);
            burger.focus();
        }
    });

    // Ekran kengayganda (masalan, telefon burilib o‘chirilsa) menyuni tiklash
    window.matchMedia("(min-width: 901px)").addEventListener("change", (event) => {
        if (event.matches) {
            setOpen(false);
            menu.classList.remove("nav-open");
            burger.classList.remove("is-active");
            burger.setAttribute("aria-expanded", "false");
        }
    });
})();
