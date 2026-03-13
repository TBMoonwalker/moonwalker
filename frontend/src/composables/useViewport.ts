import { computed, onMounted, onUnmounted, ref } from 'vue'

export function useViewport() {
    const viewportWidth = ref(window.innerWidth)

    const handleResize = () => {
        viewportWidth.value = window.innerWidth
    }

    onMounted(() => {
        window.addEventListener('resize', handleResize)
    })

    onUnmounted(() => {
        window.removeEventListener('resize', handleResize)
    })

    return {
        viewportWidth,
        isMobile: computed(() => viewportWidth.value < 768),
        isTablet: computed(
            () => viewportWidth.value >= 768 && viewportWidth.value < 1200,
        ),
    }
}
