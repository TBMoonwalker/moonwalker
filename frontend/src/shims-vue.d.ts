// fix errors - see: https://stackoverflow.com/questions/70895690/ts2307-cannot-find-module-app-vue-or-its-corresponding-type-declarations
declare module '*.vue' {
    import type { DefineComponent } from 'vue'
    const component: DefineComponent<{}, {}, any>
    export default component
}