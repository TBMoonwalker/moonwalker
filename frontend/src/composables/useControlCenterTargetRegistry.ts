import { shallowRef, type ShallowRef } from 'vue'

import {
    CONTROL_CENTER_TARGETS,
    type ControlCenterTarget,
} from '../control-center/types'

type TargetElementMap = Record<
    ControlCenterTarget,
    ShallowRef<HTMLElement | null>
>

function createTargetElementMap(): TargetElementMap {
    return CONTROL_CENTER_TARGETS.reduce((elements, target) => {
        elements[target] = shallowRef<HTMLElement | null>(null)
        return elements
    }, {} as TargetElementMap)
}

function toHtmlElement(element: Element | null): HTMLElement | null {
    if (typeof HTMLElement === 'undefined') {
        return null
    }
    return element instanceof HTMLElement ? element : null
}

export function useControlCenterTargetRegistry() {
    const targetElements = createTargetElementMap()

    function bindTargetElement(target: ControlCenterTarget) {
        return (element: Element | null) => {
            targetElements[target].value = toHtmlElement(element)
        }
    }

    function readTargetElement(target: ControlCenterTarget): HTMLElement | null {
        return targetElements[target].value
    }

    return {
        bindTargetElement,
        readTargetElement,
    }
}
