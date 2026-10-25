import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick, ref } from 'vue'
import { expect, it, vi } from 'vitest'
import { bindConfigSectionForm, type ConfigSectionFormExpose } from '../src/composables/useConfigValidationFlow'

it('binds exposed validation through a callback prop and clears it on unmount', async () => {
  const validate = vi.fn(async () => false)
  const form = ref<ConfigSectionFormExpose | null>(null)
  const show = ref(true)
  const Section = defineComponent({ setup(_, { expose }) {
    expose({ validate })
    return () => h('div')
  } })
  const bind = bindConfigSectionForm(form)
  const Relay = defineComponent({
    props: { binding: { type: Function, required: true } },
    setup(props) { return () => h(Section, { ref: instance => props.binding(instance) }) },
  })
  const view = mount(defineComponent({ setup() {
    return () => show.value ? h(Relay, { binding: bind }) : null
  } }))
  expect(await form.value?.validate()).toBe(false)
  expect(validate).toHaveBeenCalledOnce()
  show.value = false
  await nextTick()
  expect(form.value).toBeNull()
  view.unmount()
})
